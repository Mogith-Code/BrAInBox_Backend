"""Initialize database tables, syllabus, and question bank for development.

Usage:
    python scripts/init_db.py
"""

import asyncio
import sqlite3
from pathlib import Path

import _bootstrap  # noqa: F401
from pgvector.sqlalchemy import Vector
from sqlalchemy import select, text

from scripts.import_question_bank import DEFAULT_FILE as QUESTIONS_FILE
from scripts.import_question_bank import run as import_questions
from scripts.seed_syllabus import DEFAULT_FILE as SYLLABUS_FILE
from scripts.seed_syllabus import seed as seed_syllabus
from shared.db.base import Base
from shared.db.models import *  # noqa: F403 (loads all models into Base.metadata)
from shared.db.models import DocumentChunk, SourceDocument, Unit, User
from shared.db.session import SessionLocal, engine
from shared.enums import DocumentStatus, SourceType, UserRole


async def main() -> None:
    print("=" * 60)
    print("BrAInBox Database Initialization")
    print("=" * 60)

    print("\n[1/5] Checking vector extension & types...")
    async with engine.connect() as conn:
        # Check pgvector or mock vector domain
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.commit()
            print("  -> pgvector extension available!")
        except Exception:
            await conn.rollback()
            await conn.execute(
                text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
                        CREATE DOMAIN vector AS float4[];
                    END IF;
                END $$;
            """)
            )
            await conn.commit()
            print("  -> Created vector type domain for development!")

        # Check for old prototype 'papers' table that lacks 'id'
        res = await conn.execute(
            text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='papers' AND column_name='id'
        """)
        )
        if not res.fetchone():
            # Old papers table exists without 'id'
            table_check = await conn.execute(
                text("""
                SELECT 1 FROM information_schema.tables WHERE table_name='papers'
            """)
            )
            if table_check.fetchone():
                print("  -> Backing up and replacing old prototype 'papers' table...")
                await conn.execute(text("DROP TABLE IF EXISTS old_papers_backup CASCADE"))
                await conn.execute(text("ALTER TABLE papers RENAME TO old_papers_backup"))
                await conn.commit()

    print("\n[2/5] Creating database tables...")
    Vector.get_col_spec = lambda self, **kw: "vector"
    async with engine.begin() as conn:
        # Omit HNSW indexes if pgvector extension is not installed
        for table in Base.metadata.tables.values():
            for idx in list(table.indexes):
                if getattr(idx, "dialect_kwargs", {}).get("postgresql_using") == "hnsw":
                    table.indexes.remove(idx)

        await conn.run_sync(Base.metadata.create_all)
    print("  -> All tables created successfully!")

    print("\n[3/5] Seeding syllabus units and topics...")
    await seed_syllabus(SYLLABUS_FILE)
    print("  -> Syllabus seeded!")

    print("\n[4/5] Importing question bank...")
    await import_questions(QUESTIONS_FILE)
    print("  -> Question bank imported!")

    print("\n[5/6] Ensuring dev user exists...")
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.firebase_uid == "dev-student"))
        ).scalar_one_or_none()
        if not user:
            user = User(
                firebase_uid="dev-student",
                email="student@dev.local",
                display_name="Dev Student",
                role=UserRole.STUDENT,
                email_verified=True,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            print("  -> Created dev-student user!")
        else:
            print("  -> dev-student user already exists.")

    print("\n[6/6] Ensuring RAG syllabus chunks are loaded...")
    async with SessionLocal() as session:
        chunk_count = (
            await session.execute(text("SELECT count(*) FROM document_chunks"))
        ).scalar() or 0
        if chunk_count == 0:
            chroma_db_path = Path("data/chroma_db/chroma.sqlite3")
            if chroma_db_path.exists():
                conn = sqlite3.connect(chroma_db_path)
                cur = conn.cursor()
                cur.execute("""
                    SELECT em.id,
                           MAX(CASE WHEN em.key = 'chroma:document' THEN em.string_value END) as doc_text,
                           MAX(CASE WHEN em.key = 'unit' THEN em.string_value END) as unit_name,
                           MAX(CASE WHEN em.key = 'unit_no' THEN em.int_value END) as unit_no,
                           MAX(CASE WHEN em.key = 'source' THEN em.string_value END) as source_file,
                           MAX(CASE WHEN em.key = 'page_start' THEN em.int_value END) as page_start
                    FROM embedding_metadata em
                    GROUP BY em.id
                """)
                rows = cur.fetchall()
                units_res = await session.execute(select(Unit))
                units = {u.number: u for u in units_res.scalars().all()}

                by_unit: dict[int, list] = {}
                for r in rows:
                    _, doc_text, unit_name, unit_no, source_file, page_start = r
                    if doc_text and unit_no:
                        by_unit.setdefault(int(unit_no), []).append(
                            (doc_text, unit_name, source_file, page_start)
                        )

                for unit_no, chunks in sorted(by_unit.items()):
                    unit = units.get(unit_no)
                    if not unit:
                        continue
                    source_file = chunks[0][2] or f"unit_{unit_no}.pdf"
                    file_key = f"syllabus/{source_file}"

                    doc = SourceDocument(
                        title=f"Unit {unit_no}: {unit.title}",
                        source_type=SourceType.SYLLABUS,
                        file_path=file_key,
                        status=DocumentStatus.READY,
                        unit_id=unit.id,
                        chunk_count=len(chunks),
                    )
                    session.add(doc)
                    await session.flush()

                    for idx, (doc_text, unit_name, _, page) in enumerate(chunks):
                        session.add(
                            DocumentChunk(
                                document_id=doc.id,
                                chunk_index=idx,
                                text=doc_text,
                                heading_path=f"Unit {unit_no} > {unit_name or unit.title}",
                                page=page or 1,
                                token_count=len(doc_text.split()),
                                unit_id=unit.id,
                            )
                        )
                await session.commit()
                print(f"  -> Loaded {len(rows)} syllabus chunks into document_chunks!")
        else:
            print(f"  -> RAG chunks already loaded ({chunk_count} chunks present).")

    print("\n" + "=" * 60)
    print("Setup Complete! You can now generate papers in /docs.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
