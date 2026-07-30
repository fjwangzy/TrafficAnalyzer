"""Decouple source geo registration and trajectory facts from road matching.

Revision ID: 20260728_0020
Revises: 20260723_0019
"""

import hashlib
import json

import sqlalchemy as sa

from alembic import op

revision = "20260728_0020"
down_revision = "20260723_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    source_geo_table = op.create_table(
        "uav_source_geo_registrations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "source_profile_id",
            sa.String(40),
            sa.ForeignKey("uav_video_sources.profile_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("coordinate_system", sa.String(16), nullable=False),
        sa.Column("coordinate_transform_version", sa.String(80), nullable=False),
        sa.Column("anchor_gcj02", sa.JSON(), nullable=False),
        sa.Column("homography_pixel_to_enu", sa.JSON(), nullable=False),
        sa.Column("registration_pose", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("camera_calibration", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("coverage_enu_m", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("residuals", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "source_profile_id", "version_no",
            name="uq_uav_source_geo_registration_version",
        ),
        sa.UniqueConstraint(
            "source_profile_id", "checksum",
            name="uq_uav_source_geo_registration_checksum",
        ),
        sa.CheckConstraint(
            "status IN ('draft','verified','rejected','retired')",
            name="ck_uav_source_geo_registration_status",
        ),
        sa.CheckConstraint(
            "coordinate_system = 'GCJ02'",
            name="ck_uav_source_geo_registration_coordinate_system",
        ),
    )
    op.create_index(
        "ix_uav_source_geo_registrations_source",
        "uav_source_geo_registrations",
        ["source_profile_id"],
    )
    op.create_index(
        "ix_uav_source_geo_registrations_status",
        "uav_source_geo_registrations",
        ["status"],
    )
    op.add_column(
        "uav_visual_registrations",
        sa.Column(
            "source_geo_registration_id",
            sa.String(40),
            sa.ForeignKey("uav_source_geo_registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_uav_visual_registrations_geo",
        "uav_visual_registrations",
        ["source_geo_registration_id"],
    )

    # Existing verified map-scoped registrations become immutable source facts.
    # Compute exactly the same canonical SHA-256 used by the runtime verifier.
    connection = op.get_bind()
    registrations = connection.execute(sa.text("""
        SELECT
            v.id, v.source_profile_id, v.map_version_id,
            v.homography_pixel_to_enu, v.registration_pose,
            v.camera_calibration, v.map_coverage_enu_m, v.residuals,
            v.created_by, v.updated_at,
            m.coordinate_system, m.coordinate_transform_version, m.anchor_gcj02
        FROM uav_visual_registrations v
        JOIN uav_channelized_map_versions m ON m.id = v.map_version_id
        WHERE v.status = 'verified'
          AND v.source_profile_id IS NOT NULL
          AND v.homography_pixel_to_enu IS NOT NULL
        ORDER BY v.source_profile_id, v.updated_at, v.id
    """)).mappings().all()
    versions: dict[str, int] = {}
    for registration in registrations:
        source_profile_id = registration["source_profile_id"]
        versions[source_profile_id] = versions.get(source_profile_id, 0) + 1
        provenance = {
            "visual_registration_id": registration["id"],
            "map_version_id": registration["map_version_id"],
            "backfill": True,
        }
        checksum_payload = {
            "schema_version": "uav.source-geo-registration/v1",
            "source_profile_id": source_profile_id,
            "coordinate_system": registration["coordinate_system"],
            "coordinate_transform_version": registration["coordinate_transform_version"],
            "anchor_gcj02": registration["anchor_gcj02"],
            "homography_pixel_to_enu": registration["homography_pixel_to_enu"],
            "registration_pose": registration["registration_pose"] or {},
            "camera_calibration": registration["camera_calibration"] or {},
            "coverage_enu_m": registration["map_coverage_enu_m"] or {},
            "residuals": registration["residuals"] or {},
            "provenance": provenance,
        }
        checksum = hashlib.sha256(json.dumps(
            checksum_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        registration_id = f"SGR-{hashlib.sha256(registration['id'].encode()).hexdigest()[:24]}"
        connection.execute(source_geo_table.insert().values(
            id=registration_id,
            source_profile_id=source_profile_id,
            version_no=versions[source_profile_id],
            status="verified",
            coordinate_system=registration["coordinate_system"],
            coordinate_transform_version=registration["coordinate_transform_version"],
            anchor_gcj02=registration["anchor_gcj02"],
            homography_pixel_to_enu=registration["homography_pixel_to_enu"],
            registration_pose=registration["registration_pose"] or {},
            camera_calibration=registration["camera_calibration"] or {},
            coverage_enu_m=registration["map_coverage_enu_m"] or {},
            residuals=registration["residuals"] or {},
            checksum=checksum,
            provenance=provenance,
            created_by=registration["created_by"],
            verified_at=registration["updated_at"],
        ))
        connection.execute(
            sa.text("""
                UPDATE uav_visual_registrations
                SET source_geo_registration_id = :registration_id
                WHERE id = :visual_registration_id
            """),
            {
                "registration_id": registration_id,
                "visual_registration_id": registration["id"],
            },
        )

    for name, column in (
        ("association_id", sa.Column("association_id", sa.String(100), nullable=True)),
        ("tracking_method", sa.Column("tracking_method", sa.String(80), nullable=True)),
        ("tracking_quality", sa.Column("tracking_quality", sa.String(24), nullable=True)),
        ("geo_reference_quality", sa.Column("geo_reference_quality", sa.String(24), nullable=True)),
        ("road_match_quality", sa.Column("road_match_quality", sa.String(32), nullable=True)),
        ("quality_reasons", sa.Column("quality_reasons", sa.JSON(), nullable=True)),
        ("geo_registration_id", sa.Column("geo_registration_id", sa.String(40), nullable=True)),
    ):
        op.add_column("uav_track_events", column)
    op.create_index("ix_uav_track_events_association", "uav_track_events", ["association_id"])
    op.create_index("ix_uav_track_events_geo_registration", "uav_track_events", ["geo_registration_id"])


def downgrade() -> None:
    raise RuntimeError("trajectory and source registration facts are intentionally irreversible")
