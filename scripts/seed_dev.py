"""Development seed: syllabus, community groups, app settings, optional admin + sample MCQs.

Safe to run many times (idempotent): rows are matched by their natural key (unit number,
topic number, concept code, group slug, config key, question text) and never duplicated.

    python scripts/seed_dev.py                    # syllabus + groups + app_config (+ admin)
    python scripts/seed_dev.py --with-samples     # also 15 sample MCQs (so the diagnostic runs)
    docker compose exec api python -m scripts.seed_dev --with-samples

Optional admin user (never hard-code real accounts):
    SEED_ADMIN_FIREBASE_UID=<uid from the Firebase console>  SEED_ADMIN_EMAIL=<email>
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Works as `python scripts/seed_dev.py` AND `python -m scripts.seed_dev` (repo root on the path)
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from shared.db.models import (  # noqa: E402
    AppConfig,
    CommunityGroup,
    Concept,
    MCQOption,
    Question,
    Topic,
    Unit,
    User,
)
from shared.db.session import SessionLocal  # noqa: E402
from shared.enums import ContentStatus, Difficulty, QuestionType, UserRole  # noqa: E402

SYLLABUS_FILE = REPO_ROOT / "data" / "syllabus" / "biology_units.json"

# Used only when data/syllabus/biology_units.json is missing.
UNIT_TITLES = [
    "Introduction to Biology",
    "Chemical and Cellular Basis of Life",
    "Evolution and Diversity of Organisms",
    "Plant Form and Function",
    "Animal Form and Function",
    "Genetics",
    "Molecular Biology and Recombinant DNA Technology",
    "Environmental Biology",
    "Microbiology",
    "Applied Biology",
]

# Added only when the key is missing, so an admin's later changes are never overwritten.
APP_CONFIG: dict[str, Any] = {
    # Real dates: TBD (null until the Department of Examinations announces them)
    "AL_EXAM_DATES": {"2026": None, "2027": None},
    "DAILY_LIMITS": {"visuals": 5, "papers": 3},
}

# 15 ORIGINAL sample MCQs (written for this project - not from past papers or NIE books).
# (unit number, question, [5 options], index of the correct option, explanation)
SAMPLE_MCQS: list[tuple[int, str, list[str], int, str]] = [
    (
        1,
        "Which of the following is shared by ALL living organisms?",
        [
            "Photosynthesis",
            "Cellular organisation",
            "Locomotion",
            "A nervous system",
            "Sexual reproduction",
        ],
        1,
        "Every organism is made of one or more cells; the other features are found only in some.",
    ),
    (
        2,
        "Which bond joins two amino acids in a polypeptide chain?",
        ["Glycosidic bond", "Ester bond", "Peptide bond", "Hydrogen bond", "Phosphodiester bond"],
        2,
        "A condensation reaction between amino acids forms a peptide bond.",
    ),
    (
        2,
        "Which organelle is the main site of aerobic ATP production in a eukaryotic cell?",
        ["Ribosome", "Golgi apparatus", "Lysosome", "Mitochondrion", "Nucleolus"],
        3,
        "The Krebs cycle and oxidative phosphorylation take place in mitochondria.",
    ),
    (
        3,
        "In the binomial name of an organism, the first word is the name of its",
        ["species", "family", "genus", "order", "kingdom"],
        2,
        "Binomial names are written as Genus species.",
    ),
    (
        4,
        "Through which structures does most water vapour leave a leaf?",
        ["Lenticels", "Stomata", "Xylem vessels", "Root hairs", "Phloem sieve tubes"],
        1,
        "Most transpiration happens through the stomata on the leaf surface.",
    ),
    (
        4,
        "Which plant hormone makes stomata close when a plant is short of water?",
        ["Auxin", "Abscisic acid", "Gibberellin", "Cytokinin", "Ethylene"],
        1,
        "Abscisic acid (ABA) is the plant's stress hormone and triggers stomatal closure.",
    ),
    (
        5,
        "In humans, where does most absorption of digested food take place?",
        ["Stomach", "Large intestine", "Small intestine", "Oesophagus", "Rectum"],
        2,
        "The villi of the small intestine give a very large surface for absorption.",
    ),
    (
        5,
        "Which blood vessel carries oxygenated blood from the lungs to the heart?",
        ["Pulmonary artery", "Pulmonary vein", "Aorta", "Vena cava", "Hepatic portal vein"],
        1,
        "The pulmonary veins return oxygenated blood to the left atrium.",
    ),
    (
        6,
        "Two pea plants that are both heterozygous for tallness (Tt) are crossed. "
        "What ratio of tall to dwarf offspring is expected?",
        ["1 : 1", "1 : 2 : 1", "3 : 1", "9 : 3 : 3 : 1", "All tall"],
        2,
        "Tt x Tt gives TT, Tt, Tt, tt: three tall to one dwarf.",
    ),
    (
        6,
        "A woman carries a recessive X-linked allele; her husband does not have it. "
        "What is the probability that their son is affected?",
        ["0", "1/4", "1/2", "3/4", "1"],
        2,
        "A son receives one of his mother's two X chromosomes, so the chance is 1/2.",
    ),
    (
        7,
        "Which enzyme joins DNA fragments together in recombinant DNA technology?",
        [
            "DNA ligase",
            "Restriction endonuclease",
            "RNA polymerase",
            "Reverse transcriptase",
            "Helicase",
        ],
        0,
        "DNA ligase seals the sugar-phosphate backbone between fragments.",
    ),
    (
        8,
        "In a food chain, which organisms are the primary consumers?",
        ["Producers", "Herbivores", "Carnivores", "Decomposers", "Top predators"],
        1,
        "Primary consumers feed directly on producers, so they are herbivores.",
    ),
    (
        9,
        "Which of the following organisms is a prokaryote?",
        ["Yeast", "Amoeba", "Escherichia coli", "Penicillium", "Chlamydomonas"],
        2,
        "E. coli is a bacterium; the others are eukaryotes.",
    ),
    (
        9,
        "Which process do microorganisms use to turn milk into yoghurt?",
        [
            "Alcoholic fermentation",
            "Lactic acid fermentation",
            "Nitrogen fixation",
            "Photosynthesis",
            "Aerobic respiration",
        ],
        1,
        "Lactic acid bacteria ferment lactose to lactic acid, which thickens the milk.",
    ),
    (
        10,
        "Which technique grows many identical plants from small pieces of plant tissue?",
        ["Hybridisation", "Tissue culture", "Cross-pollination", "Seed dormancy", "Crop rotation"],
        1,
        "Plant tissue culture (micropropagation) produces clones from explants.",
    ),
]
LETTERS = "ABCDE"


@dataclass
class Counts:
    """What the seed added (printed at the end)."""

    added: dict[str, int] = field(default_factory=dict)

    def add(self, what: str, n: int = 1) -> None:
        self.added[what] = self.added.get(what, 0) + n


# --------------------------------------------------------------------------- syllabus


async def seed_syllabus(session: AsyncSession, counts: Counts) -> dict[int, Unit]:
    """Units -> topics -> concepts from the JSON file (or only the 10 units)."""
    if SYLLABUS_FILE.exists():
        units_data = json.loads(SYLLABUS_FILE.read_text(encoding="utf-8"))["units"]
    else:
        print(f"WARNING: {SYLLABUS_FILE} not found - adding only the 10 units.")
        print("         Topics and concepts are still to be filled in.")
        units_data = [{"number": i, "title": t} for i, t in enumerate(UNIT_TITLES, start=1)]

    units: dict[int, Unit] = {}
    for unit_data in units_data:
        unit = (
            await session.execute(select(Unit).where(Unit.number == unit_data["number"]))
        ).scalar_one_or_none()
        if unit is None:
            unit = Unit(number=unit_data["number"], title=unit_data["title"])
            session.add(unit)
            await session.flush()  # gives the unit its id
            counts.add("units")
        unit.title = unit_data["title"]
        unit.description = unit_data.get("description")
        unit.exam_weight = float(unit_data.get("exam_weight", 1.0))
        units[unit.number] = unit

        for index, topic_data in enumerate(unit_data.get("topics", [])):
            topic = (
                await session.execute(
                    select(Topic).where(
                        Topic.unit_id == unit.id, Topic.number == topic_data["number"]
                    )
                )
            ).scalar_one_or_none()
            if topic is None:
                topic = Topic(unit_id=unit.id, number=topic_data["number"], title="")
                session.add(topic)
                await session.flush()
                counts.add("topics")
            topic.title = topic_data["title"]
            topic.description = topic_data.get("description")
            topic.order_index = index

            # Optional in the JSON: "concepts": [{"code": "6.2.1", "name": "..."}]
            for c_index, concept_data in enumerate(topic_data.get("concepts", [])):
                concept = (
                    await session.execute(
                        select(Concept).where(Concept.code == concept_data["code"])
                    )
                ).scalar_one_or_none()
                if concept is None:
                    concept = Concept(topic_id=topic.id, code=concept_data["code"], name="")
                    session.add(concept)
                    counts.add("concepts")
                concept.name = concept_data["name"]
                concept.description = concept_data.get("description")
                concept.learning_outcome = concept_data.get("learning_outcome")
                concept.order_index = c_index
    await session.flush()
    return units


# --------------------------------------------------------------------------- community + config


async def seed_groups(session: AsyncSession, units: dict[int, Unit], counts: Counts) -> None:
    """A "General" group (the default) plus one group per unit."""
    wanted = [("general", "General", None, True)] + [
        (f"unit-{n}", f"Unit {n}: {u.title}", u.id, False) for n, u in sorted(units.items())
    ]
    for slug, name, unit_id, is_default in wanted:
        group = (
            await session.execute(select(CommunityGroup).where(CommunityGroup.slug == slug))
        ).scalar_one_or_none()
        if group is None:
            group = CommunityGroup(slug=slug, name=name)
            session.add(group)
            counts.add("community_groups")
        group.name = name
        group.unit_id = unit_id
        group.is_default = is_default


async def seed_app_config(session: AsyncSession, counts: Counts) -> None:
    for key, value in APP_CONFIG.items():
        if await session.get(AppConfig, key) is None:
            session.add(AppConfig(key=key, value=value))
            counts.add("app_config")


async def seed_admin(session: AsyncSession, counts: Counts) -> None:
    """Only when SEED_ADMIN_FIREBASE_UID and SEED_ADMIN_EMAIL are both set."""
    uid = os.environ.get("SEED_ADMIN_FIREBASE_UID", "").strip()
    email = os.environ.get("SEED_ADMIN_EMAIL", "").strip().lower()
    if not uid or not email:
        print("No admin seeded (set SEED_ADMIN_FIREBASE_UID and SEED_ADMIN_EMAIL to add one).")
        return
    user = (
        await session.execute(select(User).where(User.firebase_uid == uid))
    ).scalar_one_or_none()
    if user is None:
        user = User(firebase_uid=uid, email=email, email_verified=True)
        session.add(user)
        counts.add("admin users")
    user.role = UserRole.ADMIN


# --------------------------------------------------------------------------- sample questions


async def seed_sample_mcqs(session: AsyncSession, units: dict[int, Unit], counts: Counts) -> None:
    """15 approved sample MCQs, each tagged to its unit and the unit's first topic."""
    for unit_number, stem, options, correct, explanation in SAMPLE_MCQS:
        unit = units.get(unit_number)
        if unit is None:
            print(f"  skipped a sample question: unit {unit_number} does not exist")
            continue
        exists = (
            await session.execute(
                select(Question.id).where(Question.source == "admin", Question.stem == stem)
            )
        ).first()
        if exists:
            continue
        # The diagnostic picks questions through their topic, so tag one if there is any.
        topic_id = (
            await session.execute(
                select(Topic.id)
                .where(Topic.unit_id == unit.id, Topic.is_outdated.is_(False))
                .order_by(Topic.order_index, Topic.number)
                .limit(1)
            )
        ).scalar_one_or_none()
        question = Question(
            unit_id=unit.id,
            topic_id=topic_id,
            question_type=QuestionType.MCQ,
            difficulty=Difficulty.EASY,
            stem=stem,
            explanation=explanation,
            marks=1,
            source="admin",
            status=ContentStatus.APPROVED,
        )
        session.add(question)
        await session.flush()
        session.add_all(
            MCQOption(question_id=question.id, label=LETTERS[i], text=text, is_correct=i == correct)
            for i, text in enumerate(options)
        )
        counts.add("sample questions")


# --------------------------------------------------------------------------- main


async def seed(with_samples: bool = False) -> Counts:
    counts = Counts()
    async with SessionLocal() as session:
        units = await seed_syllabus(session, counts)
        await seed_groups(session, units, counts)
        await seed_app_config(session, counts)
        await seed_admin(session, counts)
        if with_samples:
            await seed_sample_mcqs(session, units, counts)
        await session.commit()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-samples", action="store_true", help="also add 15 original sample MCQs"
    )
    args = parser.parse_args()
    counts = asyncio.run(seed(with_samples=args.with_samples))
    if counts.added:
        for what, n in counts.added.items():
            print(f"  added {n} {what}")
    else:
        print("  nothing to add - the database is already seeded")
    print("Done.")


if __name__ == "__main__":
    main()
