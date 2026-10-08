from sqlmodel import SQLModel, create_engine, Session, select
from typing import List, Optional
import os
import shutil
import time
from config import DATABASE_URL, DATA_DIR
from models import DownloadTask

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False, "timeout": 30})

_SQLITE_PATH = DATABASE_URL[len("sqlite:///"):] if DATABASE_URL.startswith("sqlite:///") else None

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    # SQLite-only tunables for homelab reliability (WAL survives crashes better
    # under concurrent readers like health checks + WebSocket loops).
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as connection:
            from sqlalchemy import text
            connection.execute(text("PRAGMA journal_mode=WAL"))
            connection.execute(text("PRAGMA busy_timeout=30000"))
            connection.execute(text("PRAGMA synchronous=NORMAL"))
            connection.commit()
    # create_all does not add columns to an existing SQLite database.
    # Keep this small migration here so upgrades remain safe for existing installs.
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as connection:
            from sqlalchemy import text
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(downloadtask)"))}
            for name, definition in {
                "total_files": "INTEGER NOT NULL DEFAULT 1",
                "completed_files": "INTEGER NOT NULL DEFAULT 0",
                "output_path": "VARCHAR",
                "total_size_mb": "FLOAT NOT NULL DEFAULT 0",
                "current_file_size_mb": "FLOAT NOT NULL DEFAULT 0",
                "current_file_name": "VARCHAR",
                "seeders": "INTEGER",
                "rd_status": "VARCHAR",
                "error_code": "INTEGER",
                "retry_count": "INTEGER NOT NULL DEFAULT 0",
                "last_retry_time": "FLOAT",
                "cleanup_error": "VARCHAR",
                "download_to_server": "BOOLEAN NOT NULL DEFAULT 1",
            }.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE downloadtask ADD COLUMN {name} {definition}"))
            connection.commit()

def get_session():
    with Session(engine) as session:
        yield session

def save_task(task: DownloadTask):
    with Session(engine) as session:
        session.add(task)
        session.commit()
        session.refresh(task)
    return task

def delete_task_db(task_id: str):
    with Session(engine) as session:
        task = session.get(DownloadTask, task_id)
        if task:
            session.delete(task)
            session.commit()
            return True
    return False

def get_all_tasks() -> List[DownloadTask]:
    with Session(engine) as session:
        return session.exec(select(DownloadTask)).all()

def get_task(task_id: str) -> Optional[DownloadTask]:
    with Session(engine) as session:
        return session.get(DownloadTask, task_id)


def backup_db(keep: int = 7) -> Optional[str]:
    """Create a timestamped SQLite backup under <data_dir>/backups. SQLite-only."""
    if not _SQLITE_PATH:
        return None
    try:
        src = _SQLITE_PATH
        if not os.path.isfile(src):
            return None
        backup_dir = os.path.join(str(DATA_DIR), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(backup_dir, f"downloads-{stamp}-{os.getpid()}.db")
        counter = 1
        while os.path.exists(dest):
            counter += 1
            dest = os.path.join(backup_dir, f"downloads-{stamp}-{os.getpid()}-{counter}.db")
        shutil.copy2(src, dest)
        existing = sorted(
            f for f in os.listdir(backup_dir) if f.startswith("downloads-") and f.endswith(".db")
        )
        for stale in existing[: max(0, len(existing) - keep)]:
            try:
                os.remove(os.path.join(backup_dir, stale))
            except OSError:
                pass
        return dest
    except OSError:
        return None
