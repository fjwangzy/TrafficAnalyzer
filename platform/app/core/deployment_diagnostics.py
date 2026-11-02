"""Controlled deployment messages: never render exception text, inputs or DSNs."""
import asyncio
import errno
import json
import re
import socket
import sys
import traceback


class DiagnosticError(RuntimeError):
    def __init__(self, code, title, action, facts=None):
        super().__init__(code)
        self.code, self.title, self.action, self.facts = code, title, action, facts or {}


def explain(stage, exc):
    if isinstance(exc, DiagnosticError):
        return dict(code=exc.code, title=exc.title, action=exc.action, facts=exc.facts)
    chain, pending, seen = [], [exc], set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        chain.append(item)
        pending.extend(value for value in (getattr(item, "orig", None), item.__cause__, item.__context__) if isinstance(value, BaseException))
    names = {type(item).__name__ for item in chain}
    state = next((str(getattr(item, "sqlstate", None) or getattr(item, "pgcode", "")) for item in chain
                  if getattr(item, "sqlstate", None) or getattr(item, "pgcode", None)), "")
    state = state if re.fullmatch(r"[A-Z0-9]{5}", state) else ""
    # Text is inspected for known signatures only; it is never included in output.
    message = " ".join(str(item) for item in chain).lower()
    facts = {"error_type": type(exc).__name__}
    if state:
        facts["sqlstate"] = state
    for item in chain:
        diagnostic = getattr(item, "diag", None)
        for field in ("schema_name", "table_name", "column_name", "constraint_name"):
            value = getattr(diagnostic, field, None)
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
                facts[field] = value
    sql_errors = {
        "28P01": ("DB_AUTH", "数据库口令认证失败", "核对对应DB/YCX账号与密码；确认账号状态及SM3认证配置。"),
        "28000": ("DB_ACCESS_RULE", "数据库登录被访问规则拒绝", "核对容器出口白名单、pg_hba.conf、账号及SSL要求。"),
        "3D000": ("DB_NOT_FOUND", "目标数据库不存在", "核对DB_NAME/YCX_DB_NAME；由DBA准备目标库，不导入本机road9覆盖生产。"),
        "3F000": ("SCHEMA_NOT_FOUND", "目标schema不存在", "核对schema配置并由DBA预建；不向public回退建表。"),
        "42501": ("DB_PERMISSION", "数据库对象或DDL权限不足", "按本检查的对象核对USAGE、SELECT或迁移所需CREATE权限；使用授权迁移账号。"),
        "42P01": ("TABLE_NOT_FOUND", "查询所需表不存在", "应用表由init-db迁移；YCX外部表须核对库/schema和路网数据版本，应用不会创建外部表。"),
        "42883": ("FUNCTION_NOT_FOUND", "数据库函数不可用", "核对PostGIS/TimescaleDB及函数所在schema、search_path和执行权限。"),
        "0A000": ("DB_FEATURE_UNSUPPORTED", "数据库功能或扩展不兼容", "核对瀚高PG内核与扩展配套版本；不能以跳过检查代替兼容。"),
        "53300": ("DB_CONNECTION_LIMIT", "数据库连接数已满", "由DBA检查连接数和连接池容量，释放异常连接。"),
        "57P03": ("DB_NOT_READY", "数据库正在启动或恢复", "确认数据库恢复完成后重试，不重复初始化或删除数据。"),
        "57014": ("DB_QUERY_TIMEOUT", "数据库查询超时或被取消", "检查数据库负载、锁等待和网络；本预检有时间上限。"),
        "08000": ("DB_CONNECTION_LOST", "数据库连接异常", "核对服务状态、容器路由和连接限制。"),
        "08003": ("DB_CONNECTION_LOST", "数据库连接已经关闭", "核对数据库重启、断连或连接池状态。"),
        "08006": ("DB_CONNECTION_LOST", "数据库连接中途断开", "核对网络、防火墙、数据库重启/切换及服务端日志。"),
        "23505": ("DB_UNIQUE_CONFLICT", "初始化出现唯一键冲突", "核对同ID现有记录及并发初始化；保留数据，不清库重试。"),
        "23503": ("DB_REFERENCE_CONFLICT", "初始化引用数据不一致", "核对迁移/源配置的依赖记录，不删除已有业务数据。"),
        "42601": ("DB_SQL_COMPATIBILITY", "数据库不接受当前SQL语法", "核对报告中的迁移/查询阶段及瀚高内核兼容性，不跳过该迁移。"),
        "42804": ("DB_TYPE_COMPATIBILITY", "数据库字段类型不兼容", "核对现有表结构与应用迁移版本，不手工清空或覆盖表。"),
        "42P07": ("MIGRATION_OBJECT_CONFLICT", "迁移目标对象已存在但版本状态不一致", "核对迁移版本表与实际对象，保留现有数据后由DBA处理。"),
        "42701": ("MIGRATION_OBJECT_CONFLICT", "迁移目标字段已存在但版本状态不一致", "核对迁移历史与已有字段，不直接删除字段重试。"),
        "40001": ("DB_TRANSACTION_RETRY", "数据库事务发生并发冲突", "排查并发初始化或业务事务，确认锁状态后重试。"),
        "40P01": ("DB_DEADLOCK", "数据库发生死锁", "由DBA排查锁等待及并发初始化；不通过删除业务数据解决。"),
    }
    kafka = {
        "SaslAuthenticationFailedError": ("KAFKA_AUTH", "Kafka SASL认证失败", "核对Kafka账号/密码以及SASL_PLAINTEXT、PLAIN配置。"),
        "SaslAuthenticationFailed": ("KAFKA_AUTH", "Kafka SASL认证失败", "核对Kafka账号/密码以及SASL_PLAINTEXT、PLAIN配置。"),
        "AuthenticationFailedError": ("KAFKA_AUTH", "Kafka认证失败", "核对Kafka账号状态、凭据和服务端认证日志。"),
        "AuthenticationMethodNotSupported": ("KAFKA_MECHANISM", "Kafka认证机制不受支持", "确认9093监听器使用SASL_PLAINTEXT/PLAIN。"),
        "UnsupportedSaslMechanismError": ("KAFKA_MECHANISM", "Kafka不支持配置的认证机制", "确认9093集群启用了PLAIN；不要退回无认证端口。"),
        "IllegalSaslStateError": ("KAFKA_LISTENER", "Kafka监听器认证状态与配置不匹配", "核对连接端口及SASL_PLAINTEXT/PLAIN，确认不是明文或其他认证监听器。"),
        "TopicAuthorizationFailedError": ("KAFKA_TOPIC_ACL", "Kafka Topic权限被拒绝", "按交付Topic清单授予Describe/Read/Write权限。"),
        "GroupAuthorizationFailedError": ("KAFKA_GROUP_ACL", "Kafka消费者组权限被拒绝", "核对uav-platform-replay-v2组的Read/Describe权限。"),
        "ClusterAuthorizationFailedError": ("KAFKA_CLUSTER_ACL", "Kafka集群操作权限被拒绝", "按平台所需能力核对集群级ACL，不授予无关管理权限。"),
        "TransactionalIdAuthorizationFailed": ("KAFKA_TRANSACTION_ACL", "Kafka事务ID权限被拒绝", "核对生产者事务ID对应的Write/Describe ACL。"),
        "KafkaConnectionError": ("KAFKA_CONNECTION", "Kafka连接失败", "核对9093、容器出口白名单、所有broker的advertised地址及DNS。"),
        "KafkaTimeoutError": ("KAFKA_TIMEOUT", "Kafka元数据请求超时", "核对全部broker的advertised地址、路由、防火墙和集群状态。"),
        "NoBrokersAvailable": ("KAFKA_CONNECTION", "没有可连接的Kafka broker", "核对9093地址、SASL配置、路由与容器出口白名单。"),
    }
    result = sql_errors.get(state)
    if state == "42501" and stage.startswith("ycx"):
        result = ("DB_PERMISSION", "YCX只读对象权限不足", "核对该YCX schema的USAGE、表SELECT及PostGIS函数EXECUTE权限；保持只读账号。")
    elif state == "42P01" and stage.startswith("ycx"):
        result = ("TABLE_NOT_FOUND", "YCX外部表不存在", "按本项完整表名核对YCX_DB_NAME、路网/指标schema和数据版本；应用迁移不会创建外部表。")
    elif state == "42P01" and stage == "database.timescaledb":
        result = ("TABLE_NOT_FOUND", "TimescaleDB信息视图不可用", "由DBA核对扩展完整性、PG内核配套版本和信息schema权限；不以应用补表替代扩展。")
    elif state == "42883" and stage == "ycx.postgis":
        result = ("FUNCTION_NOT_FOUND", "YCX会话找不到PostGIS版本函数", "核对YCX库的PostGIS扩展、函数所在schema、search_path及EXECUTE权限。")
    if result is None and stage.startswith("kafka"):
        result = next((value for name, value in kafka.items() if name in names), None)
    if result is None:
        if any(isinstance(item, socket.gaierror) for item in chain):
            result = ("DNS_FAILED", "主机名无法解析", "核对容器内DNS和配置的服务地址。")
        elif any(isinstance(item, (TimeoutError, asyncio.TimeoutError)) for item in chain) or names & {"ConnectionTimeout", "TimeoutExpired"}:
            result = ("CONNECTION_TIMEOUT", "连接或检查超时", "核对本检查对应服务的端口、路由、白名单及服务负载；超时本身不能证明口令错误。")
        elif ("authentication method" in message and "not supported" in message) or ("sm3" in message and "not support" in message):
            result = ("HIGHGO_AUTH_DRIVER", "当前数据库驱动不支持服务端认证方式", "确认加载/opt/highgo/lib厂商ARM64国密libpq，而非标准或x86_64库。")
        elif "no pg_hba.conf entry" in message:
            result = ("DB_ACCESS_RULE", "数据库访问白名单不匹配", "核对容器实际出口IP、pg_hba.conf及SSL要求。")
        elif "password authentication failed" in message:
            result = ("DB_AUTH", "数据库账号/口令认证失败", "核对本检查对应的DB/YCX账号、密码、账号状态及服务端认证日志。")
        elif "no password supplied" in message:
            result = ("DB_AUTH_CONFIG", "数据库连接没有提供口令", "填写该连接的DB或YCX_DB_PASSWORD，确认根.env被正确读取。")
        elif re.search(r'database [^\n]+ does not exist', message):
            result = ("DB_NOT_FOUND", "配置的数据库不存在", "核对DB_NAME/YCX_DB_NAME及连接地址，由DBA预建目标库。")
        elif "could not translate host name" in message or "name or service not known" in message:
            result = ("DNS_FAILED", "数据库主机名无法解析", "核对容器内DNS和DB/YCX连接地址。")
        elif "certificate verify failed" in message or "ssl error" in message or "ssl was required" in message:
            result = ("TLS_FAILED", "TLS连接或证书校验失败", "核对SSL模式、证书链、域名和系统时间，不关闭证书校验掩盖问题。")
        elif any(getattr(item, "errno", None) == errno.ECONNREFUSED for item in chain) or "connection refused" in message:
            result = ("CONNECTION_REFUSED", "服务端口拒绝连接", "确认目标服务监听地址/端口及容器路由、防火墙。")
        elif any(getattr(item, "errno", None) == errno.ENOSPC for item in chain):
            result = ("DISK_FULL", "持久化目录磁盘空间不足", "检查对应目录的可用空间和保留策略；不要直接删除证据或spool。")
        elif any(getattr(item, "errno", None) in {errno.EMFILE, errno.ENFILE} for item in chain):
            result = ("FILE_DESCRIPTOR_LIMIT", "文件描述符数量已达上限", "核对ulimit与容器限制，并排查文件/连接泄漏。")
        elif any(isinstance(item, PermissionError) or getattr(item, "errno", None) == errno.EROFS for item in chain):
            result = ("PATH_PERMISSION", "路径无权限或挂载为只读", "核对本检查目录的属主/权限及Compose挂载；模型只读，输出/上传/spool须可写。")
        elif any(isinstance(item, FileNotFoundError) for item in chain):
            result = ("FILE_MISSING", "检查所需文件或目录不存在", "核对报告中的文件/挂载路径，按对应离线资源清单完整拷贝。")
        elif names & {"ImportError", "ModuleNotFoundError"} or "undefined symbol" in message or "cannot open shared object" in message:
            result = ("RUNTIME_DEPENDENCY", "运行库或动态库缺失/ABI不匹配", "使用本版本ARM64离线镜像及配套驱动，核对CANN/国密库依赖，不在隔离现场联网pip修补。")
        elif "could not determine version from string" in message:
            result = ("DB_DIALECT_OLD", "仍在使用不支持瀚高横幅的旧版本解析器", "确认生产容器加载HighGoPsycopgDialect和最新只读源码挂载，使用累计修复脚本重建应用容器。")
        elif "numeric server_version_num" in message:
            result = ("DB_VERSION_NUMBER", "服务端没有返回合法数字PG内核版本", "由DBA核对SHOW server_version_num；不能把瀚高产品版本当成PG内核或写死版本号。")
        elif "expected timescaledb hypertables are missing" in message:
            result = ("HYPERTABLE_MISSING", "迁移后应用schema中的Timescale超表不完整", "核对迁移日志、扩展兼容性及create_hypertable权限；不要直接改版本表标记成功。")
        elif "migrations are not current" in message:
            result = ("MIGRATION_INCOMPLETE", "基础或Replay V2数据库版本未就绪", "检查init-db各迁移阶段及迁移权限；不在普通Platform启动中隐式补表。")
        elif stage.startswith("models") and "ValueError" in names:
            result = ("MODEL_MANIFEST", "模型清单、尺寸或哈希校验失败", "按MODEL_SHA256SUMS核对完整模型包及640/960/1280三档OM，不使用单独PT替代。")
        elif stage.startswith("ascend"):
            code = re.search(r"code=(\d+)", message)
            if code:
                facts["ascend_code"] = int(code[1])
            result = ("ASCEND_EXECUTION", "昇腾设备/模型操作失败", "按本检查的加载或尺寸阶段及原生错误码核对npu-smi、驱动/CANN9.0.0、310P3模型、设备号和显存；不回退CPU。")
        elif stage == "configuration" or stage.endswith(".configuration"):
            result = ("CONFIG_INVALID", "生产配置缺失或格式不合法", "核对根.env的必填项、JSON CORS/允许主机列表、schema标识符及非默认密码。")
            if hasattr(exc, "errors"):
                errors = exc.errors(include_input=False, include_url=False)
                facts["fields"] = [".".join(map(str, item["loc"])) or "deployment configuration" for item in errors]
                if any(item["type"] in {"int_parsing", "int_type"} for item in errors):
                    result = ("CONFIG_INTEGER", "配置字段应为整数", "按列出的字段核对端口、设备号和处理尺寸，不填写带单位或空字符串。")
                elif any(item["type"] == "literal_error" for item in errors):
                    result = ("CONFIG_ENUM", "配置枚举值不受支持", "按.env模板核对DB_DRIVER、部署模式、SSL模式及Kafka认证机制。")
                fixed = {
                    "SASL Kafka requires username and password": ("CONFIG_KAFKA_CREDENTIALS", "Kafka SASL账号或密码缺失", "填写KAFKA_SASL_USERNAME和KAFKA_SASL_PASSWORD。"),
                    "uat/production requires an explicit CORS origin allowlist": ("CONFIG_CORS", "生产CORS来源列表无效", "填写明确JSON来源列表或首次通过项目启动脚本将auto转换为现场IP。"),
                    "uat/production requires secure media cookies": ("CONFIG_COOKIE", "Cookie设置与HTTP部署模式不匹配", "内网HTTP须显式启用INTRANET_HTTP_ENABLED；HTTPS按手册启用Secure Cookie。"),
                    "uat/production requires a non-default DB password": ("CONFIG_DB_SECRET", "生产数据库密码缺失或仍为开发默认值", "填写已授权的生产口令，不修改本地开发.env。"),
                    "uat/production requires a non-default JWT secret": ("CONFIG_JWT_SECRET", "生产JWT密钥缺失或仍为默认值", "填写生产JWT_SECRET_KEY，升级时保留现有密钥以避免会话失效。"),
                    "uat/production requires a non-default bootstrap admin password": ("CONFIG_ADMIN_SECRET", "初始管理员密码仍为默认值", "填写BOOTSTRAP_ADMIN_PASSWORD；既有账号不会被重置。"),
                }
                for error in errors:
                    reason = error.get("msg", "").removeprefix("Value error, ")
                    if reason in fixed:
                        result = fixed[reason]
                        break
        else:
            result = ("ENV_UNKNOWN", "未分类异常，当前证据不足以判断原因", "保留本次自动报告及代码位置进一步定位；不要盲目更换驱动、放宽权限或跳过检查。")
    code, title, action = result
    return dict(code=code, title=title, action=action, facts=facts,
                locations=[f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in traceback.extract_tb(exc.__traceback__)[-5:]])


class Report:
    def __init__(self):
        self.checks = []

    def add(self, stage, status, **details):
        self.checks.append(dict(stage=stage, status=status, **details))

    def skip(self, stage, reason):
        self.add(stage, "skipped", code="DEPENDENCY_UNAVAILABLE", title=reason)

    def error(self, stage, exc):
        self.add(stage, "failed", **explain(stage, exc))

    def run(self, stage, function):
        print("Preflight: " + stage, file=sys.stderr, flush=True)
        try:
            result = function()
        except Exception as exc:
            self.error(stage, exc)
            return None
        self.add(stage, "passed", facts=result if isinstance(result, dict) else {})
        return result

    async def arun(self, stage, function, timeout=20, *, optional=False):
        print("Preflight: " + stage, file=sys.stderr, flush=True)
        try:
            result = await asyncio.wait_for(function(), timeout)
        except Exception as exc:
            self.error(stage, exc)
            if optional:
                self.checks[-1]["status"] = "warning"
                self.checks[-1]["action"] += " 本项为可选依赖，不阻止平台启动。"
            return None
        self.add(stage, "passed", facts=result if isinstance(result, dict) else {})
        return result

    @property
    def failed(self):
        return any(item["status"] == "failed" for item in self.checks)

    def emit(self):
        counts = {status: sum(item["status"] == status for item in self.checks)
                  for status in ("passed", "failed", "warning", "skipped", "pending_init")}
        print(json.dumps({"schema_version": "uav.deployment-checks/v1", "ok": not self.failed,
                          "summary": counts, "checks": self.checks}, ensure_ascii=False, indent=2), flush=True)
        print("预检汇总：" + json.dumps(counts, ensure_ascii=False), file=sys.stderr, flush=True)
        for item in self.checks:
            if item["status"] in {"failed", "warning", "skipped"}:
                line = f"DIAGNOSTIC [{item.get('code', item['status'])}] {item['stage']}: {item.get('title', '')}"
                if item.get("action"):
                    line += " | 处理：" + item["action"]
                if item.get("facts"):
                    line += " | 证据：" + json.dumps(item["facts"], ensure_ascii=False)
                if item.get("locations") and item.get("code") in {"ENV_UNKNOWN", "ASCEND_EXECUTION"}:
                    line += " | 代码位置：" + json.dumps(item["locations"], ensure_ascii=False)
                print(line, file=sys.stderr)
        sys.stderr.flush()
