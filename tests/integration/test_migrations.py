"""Integration tests for Alembic database migration execution."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_alembic_config_loading():
    """Verify alembic.ini is present and can be parsed."""
    project_root = Path(__file__).resolve().parent.parent.parent
    ini_path = project_root / "alembic.ini"
    assert ini_path.exists(), "alembic.ini must exist in project root"

    alembic_cfg = Config(str(ini_path))
    script_loc = alembic_cfg.get_main_option("script_location")
    assert script_loc == "migrations"


def test_alembic_migration_upgrade_and_downgrade(tmp_path: Path):
    """Verify migrations can upgrade, downgrade stepwise, and re-upgrade."""
    project_root = Path(__file__).resolve().parent.parent.parent
    ini_path = project_root / "alembic.ini"

    test_db_path = tmp_path / "test_migration.db"
    sync_test_url = f"sqlite:///{test_db_path}"

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", sync_test_url)

    os.environ["DATABASE_URL"] = sync_test_url

    try:
        # 1. Upgrade to head (applies 0001 through 0007)
        command.upgrade(alembic_cfg, "head")

        # 2. Stepwise downgrade -1 (downgrades 0007 to 0006)
        command.downgrade(alembic_cfg, "-1")

        # 3. Stepwise downgrade -1 (downgrades 0006 to 0005)
        command.downgrade(alembic_cfg, "-1")

        # 4. Stepwise downgrade -1 (downgrades 0005 to 0004)
        command.downgrade(alembic_cfg, "-1")

        # 5. Stepwise downgrade -1 (downgrades 0004 to 0003)
        command.downgrade(alembic_cfg, "-1")

        # 6. Stepwise downgrade -1 (downgrades 0003 to 0002)
        command.downgrade(alembic_cfg, "-1")

        # 7. Stepwise downgrade -1 (downgrades 0002 to 0001)
        command.downgrade(alembic_cfg, "-1")

        # 8. Re-upgrade to head
        command.upgrade(alembic_cfg, "head")

        # 9. Full downgrade to base
        command.downgrade(alembic_cfg, "base")

        # 10. Final re-upgrade back to head
        command.upgrade(alembic_cfg, "head")
    finally:
        os.environ.pop("DATABASE_URL", None)
