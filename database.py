from sqlmodel import SQLModel, create_engine, Session, select
from typing import List, Optional
from config import DATABASE_URL
from models import DownloadTask

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
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
