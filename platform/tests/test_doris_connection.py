import json
import sys
from types import SimpleNamespace

import pytest

from app.core.doris_connection import query
from app.core.deployment_diagnostics import DiagnosticError, Report


@pytest.mark.asyncio
@pytest.mark.parametrize('number,code', [(1045,'DORIS_AUTH'),(1142,'DORIS_PERMISSION'),(1146,'DORIS_TABLE'),(1049,'DORIS_DATABASE'),(2013,'DORIS_TIMEOUT'),(9999,'DORIS_QUERY')])
async def test_doris_error_is_optional_redacted_and_closes_connection(monkeypatch, number, code, capsys):
    calls = []
    class Error(Exception): pass
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def execute(self, sql, parameters):
            assert parameters == ('literal $ and quote \'',)
            raise Error(number, 'private-password SQL DSN must never be printed')
    class Connection:
        def cursor(self): return Cursor()
        def close(self): calls.append('closed')
    def connect(**kwargs):
        assert kwargs['port'] == 9030 and kwargs['database'] == 'ycx_xc'
        assert kwargs['autocommit'] is True and kwargs['read_timeout'] == 10
        return Connection()
    monkeypatch.setitem(sys.modules, 'pymysql', SimpleNamespace(Error=Error, connect=connect, cursors=SimpleNamespace(DictCursor=object)))
    settings = SimpleNamespace(doris_mysql_host='fixture', doris_mysql_port=9030, doris_mysql_user='reader',
        doris_mysql_password='private-password', doris_database='ycx_xc')
    report = Report()
    await report.arun('doris.metrics', lambda: query(settings, 'SELECT * FROM `ycx_xc`.`fixture` WHERE id=%s', 'literal $ and quote \''), optional=True)
    assert not report.failed and calls == ['closed']
    assert report.checks[0]['code'] == code and report.checks[0]['status'] == 'warning'
    report.emit()
    output = capsys.readouterr()
    assert 'private-password' not in output.out + output.err and 'DSN' not in output.out + output.err


@pytest.mark.asyncio
async def test_doris_rejects_writes_and_unconfigured_connection_before_driver_import():
    settings = SimpleNamespace(doris_mysql_host='fixture', doris_mysql_user='reader', doris_database='ycx_xc')
    with pytest.raises(ValueError, match='SELECT-only'):
        await query(settings, 'DELETE FROM business')
    settings.doris_mysql_host = ''
    with pytest.raises(DiagnosticError, match='DORIS_NOT_CONFIGURED'):
        await query(settings, 'SELECT 1')


@pytest.mark.asyncio
async def test_doris_version_is_enabled_not_is_enable_and_never_guesses(monkeypatch):
    from app.core import doris_connection
    calls = []
    async def fetch(settings,sql,*args):
        calls.append(sql)
        assert 'is_enabled=1' in sql and 'MAX(' not in sql
        return []
    monkeypatch.setattr(doris_connection, 'query', fetch)
    settings = SimpleNamespace(doris_database='ycx_xc',ycx_road_version='confirmed')
    assert await doris_connection.active_road_version(settings) == 'confirmed'
    assert await doris_connection.active_road_version(settings,'explicit') == 'explicit'
    assert not calls
    settings.ycx_road_version = ''
    with pytest.raises(DiagnosticError,match='YCX_VERSION_UNAVAILABLE'):
        await doris_connection.active_road_version(settings)


def test_doris_wkt_uses_existing_geometry_parser_and_rejects_bad_data():
    from app.core.doris_connection import geometry_geojson
    assert geometry_geojson(None) is None
    assert geometry_geojson(' ') is None
    assert geometry_geojson('POINT EMPTY') is None
    assert json.loads(geometry_geojson('POINT(117 36)')) == {'type':'Point','coordinates':[117,36]}
    with pytest.raises(DiagnosticError,match='DORIS_GEOMETRY'):
        geometry_geojson('bad geometry')


@pytest.mark.asyncio
async def test_doris_rejects_database_identifier_injection_before_connect():
    settings = SimpleNamespace(doris_mysql_host='fixture',doris_mysql_user='root',doris_database='db`; DROP TABLE facts;--')
    with pytest.raises(ValueError,match='identifier'):
        await query(settings,'SELECT 1')
