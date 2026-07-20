import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.services.pipeline_manager import PipelineInstance, PipelineManager, PipelineStatus


class _EmptyStream:
    async def read(self, _size):
        return b""


class _FakeProcess:
    pid = 4321
    returncode = None
    stdout = _EmptyStream()
    stderr = _EmptyStream()


class PipelineManagerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        task = getattr(self, "_monitor_task", None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def test_start_pipeline_builds_detector_command_and_environment(self):
        captured = {}
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        project_root = Path(temp_dir.name)
        video_path = project_root / "test_videos/inter_xqh/demo.mp4"
        telemetry_path = project_root / "test_videos/mp4new/srt/海右路 0624.txt"
        video_path.parent.mkdir(parents=True)
        telemetry_path.parent.mkdir(parents=True)
        video_path.write_bytes(b"test")
        telemetry_path.write_text("test")

        async def fake_exec(*cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs["cwd"]
            captured["env"] = kwargs["env"]
            captured["start_new_session"] = kwargs["start_new_session"]
            return _FakeProcess()

        manager = PipelineManager(
            project_root=project_root,
            kafka_bootstrap="kafka:29092",
            pipeline_python="/opt/pipeline/bin/python",
            frame_stride=12,
        )

        with patch(
            "app.services.pipeline_manager.asyncio.create_subprocess_exec",
            side_effect=fake_exec,
        ):
            pipeline = await manager.start_pipeline(
                drone_id="drone_1",
                intersection_id="INT_camera_1",
                video_src="test_videos/inter_xqh/demo.mp4",
                roads_json="",
                telemetry_source="srt",
                telemetry_file_path="test_videos/mp4new/srt/海右路 0624.txt",
                telemetry_time_offset_sec=12.25,
                telemetry_sync_tolerance_sec=2.5,
                kafka_bootstrap="kafka:29092",
                mission_id="MIS-REAL-001",
                source_profile_id="SRC-REAL-001",
                inter_id="INT_camera_1",
                road_data_version="road-v1",
                road_context_status="complete",
                quality_status="verified",
            )

        self._monitor_task = manager._monitor_task

        self.assertEqual(pipeline.status, PipelineStatus.RUNNING)
        self.assertEqual(captured["cwd"], str(project_root))
        self.assertTrue(captured["start_new_session"])
        self.assertEqual(
            captured["cmd"],
            (
                "/opt/pipeline/bin/python",
                "main_optimized.py",
                "pipeline.send_info_kafka=True",
                "hydra/job_logging=disabled",
                "telemetry.enabled=True",
                "telemetry.source=srt",
                f"telemetry.file_path='{telemetry_path.resolve()}'",
                "telemetry.time_offset_sec=12.25",
                "telemetry.sync_tolerance_sec=2.5",
            ),
        )
        self.assertEqual(captured["env"]["VIDEO_SRC"], str(video_path.resolve()))
        self.assertEqual(captured["env"]["ROADS_JSON"], "")
        self.assertEqual(captured["env"]["TOPIC_NAME"], "uav_statistics_10")
        self.assertEqual(captured["env"]["CAMERA_ID"], "10")
        self.assertEqual(captured["env"]["DRONE_ID"], "drone_1")
        self.assertEqual(captured["env"]["INTERSECTION_ID"], "INT_camera_1")
        self.assertEqual(captured["env"]["INTER_ID"], "INT_camera_1")
        self.assertEqual(captured["env"]["MISSION_ID"], "MIS-REAL-001")
        self.assertEqual(captured["env"]["PIPELINE_ID"], pipeline.pipeline_id)
        self.assertEqual(captured["env"]["RUN_ID"], pipeline.pipeline_id)
        self.assertEqual(captured["env"]["SOURCE_PROFILE_ID"], "SRC-REAL-001")
        self.assertEqual(captured["env"]["ROAD_DATA_VERSION"], "road-v1")
        self.assertEqual(captured["env"]["ROAD_CONTEXT_STATUS"], "complete")
        self.assertEqual(captured["env"]["QUALITY_STATUS"], "verified")
        self.assertEqual(captured["env"]["VIDEO_PORT"], "8101")
        self.assertEqual(captured["env"]["FRAME_STRIDE"], "12")
        self.assertEqual(captured["env"]["KAFKA_BOOTSTRAP"], "kafka:29092")

    def test_rtsp_and_roads_sources_use_explicit_allowlists(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        project_root = Path(temp_dir.name)
        roads_root = project_root / "generated-roads"
        roads_root.mkdir()
        roads_path = roads_root / "intersection.json"
        roads_path.write_text("{}")
        manager = PipelineManager(project_root=project_root)

        with (
            patch.object(settings, "uav_rtsp_allowed_hosts", ["camera.uat.internal"]),
            patch.object(settings, "pipeline_roads_roots", [str(roads_root)]),
        ):
            self.assertEqual(
                manager._validate_video_source("rtsp://camera.uat.internal/live"),
                "rtsp://camera.uat.internal/live",
            )
            with self.assertRaisesRegex(ValueError, "RTSP host"):
                manager._validate_video_source("rtsp://evil.example/live")
            self.assertEqual(
                manager._validate_support_file(
                    str(roads_path), (".json",), roots=manager._roads_roots()
                ),
                str(roads_path.resolve()),
            )

    async def test_pipeline_start_rejects_nonempty_lane_annotation_parameters(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        project_root = Path(temp_dir.name)
        video_path = project_root / "test_videos/demo.mp4"
        video_path.parent.mkdir(parents=True)
        video_path.write_bytes(b"test")
        manager = PipelineManager(project_root=project_root)

        with self.assertRaisesRegex(ValueError, "roads_json must be empty"):
            await manager.start_pipeline(
                drone_id="drone_1",
                intersection_id="INT-1",
                video_src="test_videos/demo.mp4",
                roads_json="configs/lanes.json",
            )

    def test_pipeline_output_never_exposes_rtsp_credentials_or_query_secret(self):
        pipeline = PipelineInstance(
            pipeline_id="pipe-redacted",
            drone_id="drone_1",
            intersection_id="INT_camera_1",
            video_src="rtsps://operator:secret@camera.uat.internal:8554/live?token=private",
            roads_json="",
            topic_name="uav_statistics_10",
            camera_id=10,
        )

        self.assertEqual(
            pipeline.to_dict()["video_src"],
            "rtsps://camera.uat.internal:8554/live",
        )

    def test_zero_return_code_marks_pipeline_stopped_not_error(self):
        manager = PipelineManager(project_root="/project")
        pipeline = PipelineInstance(
            pipeline_id="pipe-ok",
            drone_id="drone_1",
            intersection_id="INT_camera_1",
            video_src="test_videos/test_video.mp4",
            roads_json="",
            topic_name="uav_statistics_10",
            camera_id=10,
            status=PipelineStatus.RUNNING,
            error_message="previous error",
        )

        manager._handle_process_exit(pipeline, 0)

        self.assertEqual(pipeline.status, PipelineStatus.STOPPED)
        self.assertEqual(pipeline.error_message, "")
        self.assertGreater(pipeline.stopped_at, 0)

    def test_nonzero_return_code_marks_pipeline_error_with_stderr_tail(self):
        manager = PipelineManager(project_root="/project")
        pipeline = PipelineInstance(
            pipeline_id="pipe-error",
            drone_id="drone_1",
            intersection_id="INT_camera_1",
            video_src="test_videos/test_video.mp4",
            roads_json="",
            topic_name="uav_statistics_10",
            camera_id=10,
            status=PipelineStatus.RUNNING,
            stderr_tail="ValueError: boom",
        )

        manager._handle_process_exit(pipeline, 1)

        self.assertEqual(pipeline.status, PipelineStatus.ERROR)
        self.assertIn("Process exited with code 1", pipeline.error_message)
        self.assertIn("ValueError: boom", pipeline.error_message)
        self.assertGreater(pipeline.stopped_at, 0)


class PlatformDeploymentConfigTest(unittest.TestCase):
    def test_platform_image_installs_pipeline_dependencies(self):
        root = Path(__file__).resolve().parents[2]
        dockerfile = (root / "Dockerfile").read_text()
        requirements = (root / "platform" / "pipeline-requirements.txt").read_text()
        constraints = (root / "platform" / "pipeline-constraints.txt").read_text()

        self.assertIn("CMD [\"python\", \"run_platform.py\"]", dockerfile)
        self.assertIn("COPY run_platform.py main_optimized.py /app/", dockerfile)
        self.assertIn("COPY services/*.py /app/services/", dockerfile)
        self.assertIn("pipeline-requirements.txt", dockerfile)
        self.assertIn("pipeline-constraints.txt", dockerfile)
        self.assertIn("torch==2.2.2", dockerfile)
        self.assertIn("torchvision==0.17.2", dockerfile)
        self.assertIn("hydra-core==1.3.2", requirements)
        self.assertIn("ultralytics>=8.3.0", requirements)
        self.assertIn("numpy<2", constraints)
        self.assertIn("torch==2.2.2", constraints)
        self.assertIn("torchvision==0.17.2", constraints)

    def test_platform_pipeline_requirements_include_root_requirements(self):
        root = Path(__file__).resolve().parents[2]

        def dependency_lines(path: Path) -> set[str]:
            return {
                line.strip()
                for line in path.read_text().splitlines()
                if line.strip() and not line.strip().startswith("#")
            }

        platform_deps = dependency_lines(root / "platform" / "pipeline-requirements.txt")
        root_deps = dependency_lines(root / "requirements.txt")

        self.assertTrue(root_deps.issubset(platform_deps))

    def test_compose_topic_patterns_include_system_metrics(self):
        root = Path(__file__).resolve().parents[2]
        compose_files = [root / "docker-compose.yaml"]

        for path in compose_files:
            with self.subTest(path=str(path)):
                text = path.read_text()
                self.assertIn("uav_system_metrics", text)
                self.assertIn("track_complete", text)
                self.assertIn("conflicts", text)
                self.assertIn("telemetry", text)

    def test_root_image_and_entrypoint_replace_platform_local_deployment_files(self):
        root = Path(__file__).resolve().parents[2]
        compose = (root / "docker-compose.yaml").read_text()
        dockerignore = (root / ".dockerignore").read_text().splitlines()
        detector_backup = (root / "Dockerfile.detector").read_text()
        root_entry = (root / "run_platform.py").read_text()

        self.assertFalse((root / "platform" / "Dockerfile").exists())
        self.assertFalse((root / "platform" / "scripts" / "run_local.py").exists())
        self.assertIn('PIPELINE_PROJECT_ROOT: /app', compose)
        self.assertIn('./weights:/app/weights:ro', compose)
        self.assertIn('./test_videos:/app/test_videos:ro', compose)
        self.assertNotIn('.:/project:ro', compose)
        self.assertIn("PIPELINE_PROJECT_ROOT", root_entry)
        self.assertIn('CMD ["python", "main_optimized.py"]', detector_backup)
        self.assertIn("test_videos", dockerignore)
        self.assertIn("weights", dockerignore)
        self.assertNotIn("services", dockerignore)

    def test_lane_annotation_auto_tasks_are_disabled_by_default_and_in_compose(self):
        root = Path(__file__).resolve().parents[2]
        compose = (root / "docker-compose.yaml").read_text()

        self.assertFalse(settings.lane_annotation_auto_tasks_enabled)
        self.assertIn('LANE_ANNOTATION_AUTO_TASKS_ENABLED: "false"', compose)


if __name__ == "__main__":
    unittest.main()
