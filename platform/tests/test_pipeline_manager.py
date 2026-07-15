import asyncio
import contextlib
import unittest
from pathlib import Path
from unittest.mock import patch

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

        async def fake_exec(*cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs["cwd"]
            captured["env"] = kwargs["env"]
            captured["start_new_session"] = kwargs["start_new_session"]
            return _FakeProcess()

        manager = PipelineManager(
            project_root="/project",
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
                telemetry_file_path="test_videos/inter_xqh/telemetry.srt",
                telemetry_time_offset_sec=12.25,
                telemetry_sync_tolerance_sec=2.5,
                kafka_bootstrap="kafka:29092",
            )

        self._monitor_task = manager._monitor_task

        self.assertEqual(pipeline.status, PipelineStatus.RUNNING)
        self.assertEqual(captured["cwd"], "/project")
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
                "telemetry.file_path=test_videos/inter_xqh/telemetry.srt",
                "telemetry.time_offset_sec=12.25",
                "telemetry.sync_tolerance_sec=2.5",
            ),
        )
        self.assertEqual(captured["env"]["VIDEO_SRC"], "test_videos/inter_xqh/demo.mp4")
        self.assertEqual(captured["env"]["ROADS_JSON"], "")
        self.assertEqual(captured["env"]["TOPIC_NAME"], "uav_statistics_10")
        self.assertEqual(captured["env"]["CAMERA_ID"], "10")
        self.assertEqual(captured["env"]["INTERSECTION_ID"], "INT_camera_1")
        self.assertEqual(captured["env"]["VIDEO_PORT"], "8101")
        self.assertEqual(captured["env"]["FRAME_STRIDE"], "12")
        self.assertEqual(captured["env"]["KAFKA_BOOTSTRAP"], "kafka:29092")

    def test_zero_return_code_marks_pipeline_stopped_not_error(self):
        manager = PipelineManager(project_root="/project")
        pipeline = PipelineInstance(
            pipeline_id="pipe-ok",
            drone_id="drone_1",
            intersection_id="INT_camera_1",
            video_src="test_videos/test_video.mp4",
            roads_json="",
            topic_name="statistics_10",
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
            topic_name="statistics_10",
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
        dockerfile = (root / "platform" / "Dockerfile").read_text()
        requirements = (root / "platform" / "pipeline-requirements.txt").read_text()
        constraints = (root / "platform" / "pipeline-constraints.txt").read_text()

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
        compose_files = [
            root / "docker-compose.yaml",
            root / "platform" / "docker" / "docker-compose.platform.yml",
        ]

        for path in compose_files:
            with self.subTest(path=str(path)):
                text = path.read_text()
                self.assertIn("system_metrics", text)
                self.assertIn("track_complete", text)
                self.assertIn("conflicts", text)
                self.assertIn("telemetry", text)


if __name__ == "__main__":
    unittest.main()
