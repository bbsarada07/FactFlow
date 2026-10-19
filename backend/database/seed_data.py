"""Seed documented incidents, their archived verdicts, and known misinformation patterns.

The forward texts are representative reconstructions of the rumours as reported
at the time, not verbatim copies; the UI labels them as such.
"""
from datetime import date, datetime, time, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Claim, Incident, KnownPattern
from services.text_utils import input_hash

INCIDENTS = [
    {
        "slug": "palghar-2020",
        "name": "Palghar Mob Lynching",
        "occurred_on": date(2020, 4, 16),
        "location": "Gadchinchale, Palghar, Maharashtra",
        "platform": "WhatsApp",
        "deaths": 3,
        "harm_type": "VIOLENCE",
        "verdict": "FALSE",
        "claim": "Gangs of child kidnappers and organ thieves are roaming villages at night.",
        "summary": (
            "During the COVID-19 lockdown, rumours spread across villages on WhatsApp that "
            "child-kidnappers and organ thieves were moving around at night. A mob stopped a car "
            "carrying two sadhus and their driver and beat all three to death in front of police."
        ),
        "what_was_true": (
            "No kidnapping or organ-theft gang existed. The victims were two Hindu sadhus and their "
            "driver passing through the area by car."
        ),
        "forward_text": (
            "ALERT!! Gangs of child kidnappers are moving in villages at night dressed as sadhus and "
            "police. They take children and remove their kidneys. Stay awake, guard your village and "
            "stop every outside vehicle. Forward to all groups!"
        ),
        "fact_check_days": 4,
        "reference_query": "Palghar mob lynching",
    },
    {
        "slug": "muzaffarnagar-2013",
        "name": "Muzaffarnagar Riots",
        "occurred_on": date(2013, 9, 7),
        "location": "Muzaffarnagar, Uttar Pradesh",
        "platform": "Facebook",
        "deaths": 62,
        "harm_type": "COMMUNAL",
        "verdict": "FALSE",
        "claim": "A video shows two young men from Kawal village being lynched by a mob.",
        "summary": (
            "After a deadly clash in Kawal village, a graphic video of two young men being beaten to "
            "death was shared as footage of the killings. It inflamed communal tension in the run-up "
            "to riots that killed at least 62 people and displaced tens of thousands."
        ),
        "what_was_true": (
            "The video was older footage of a lynching in Sialkot, Pakistan, unrelated to Kawal or "
            "Muzaffarnagar."
        ),
        "forward_text": (
            "Watch how they killed our boys in Kawal. Share this video so everyone sees what was done "
            "to them. Don't stay silent!"
        ),
        "fact_check_days": None,
        "reference_query": "2013 Muzaffarnagar riots",
    },
    {
        "slug": "dhule-2018",
        "name": "Rainpada (Dhule) Lynching",
        "occurred_on": date(2018, 7, 1),
        "location": "Rainpada, Dhule, Maharashtra",
        "platform": "WhatsApp",
        "deaths": 5,
        "harm_type": "VIOLENCE",
        "verdict": "FALSE",
        "claim": "A child-kidnapping gang disguised as beggars has entered the district.",
        "summary": (
            "WhatsApp messages warning of child-kidnapping gangs had circulated in the region for "
            "weeks. When five men from a nomadic community stopped at a weekly market, a crowd accused "
            "them of being kidnappers and beat them to death."
        ),
        "what_was_true": (
            "There was no kidnapping gang. The five victims were members of a nomadic community who had "
            "come to the market seeking alms."
        ),
        "forward_text": (
            "Child kidnapping gang has entered our district. Many members, dressed as beggars. They "
            "kidnap children and sell their organs. Share in all groups and stay alert!"
        ),
        "fact_check_days": None,
        "reference_query": "Dhule lynching 2018",
    },
    {
        "slug": "covid-communal-2020",
        "name": "COVID-19 'Spitting' Videos",
        "occurred_on": date(2020, 4, 5),
        "location": "Nationwide",
        "platform": "WhatsApp / Twitter",
        "deaths": 0,
        "harm_type": "COMMUNAL",
        "verdict": "FALSE",
        "claim": "Videos show Muslims deliberately spitting on food to spread COVID-19.",
        "summary": (
            "After a COVID-19 cluster was linked to a religious gathering in Delhi, unrelated and "
            "staged videos were shared claiming Muslims were spitting on food to spread the virus. "
            "The wave fuelled boycotts of and assaults on Muslim vendors."
        ),
        "what_was_true": (
            "Fact-checkers traced the videos to other countries, earlier years or staged scenes; none "
            "showed deliberate spreading of COVID-19."
        ),
        "forward_text": (
            "SHOCKING video: see how they are spitting on fruits to spread corona. Don't buy from them. "
            "Forward to save your family."
        ),
        "fact_check_days": None,
        "reference_query": "Tablighi Jamaat coronavirus misinformation",
    },
    {
        "slug": "manipur-2023",
        "name": "Manipur Fake Photo",
        "occurred_on": date(2023, 5, 4),
        "location": "B. Phainom, Kangpokpi, Manipur",
        "platform": "WhatsApp / Facebook",
        "deaths": 2,
        "harm_type": "COMMUNAL",
        "verdict": "FALSE",
        "claim": "A photo shows a Meitei woman murdered by Kuki men in Churachandpur.",
        "summary": (
            "As ethnic violence broke out, a photo of a woman's body wrapped in plastic was shared with "
            "the claim that a Meitei woman had been killed in Churachandpur. Police said the rumour "
            "preceded a mob attack in B. Phainom village in which two men were killed and two women "
            "were paraded and assaulted."
        ),
        "what_was_true": "The photo came from an unrelated murder case outside Manipur.",
        "forward_text": (
            "Our sister was raped and killed in Churachandpur. Look at what they did to her body. "
            "We cannot keep quiet any more. Share widely."
        ),
        "fact_check_days": None,
        "reference_query": "2023 Manipur violence",
    },
    {
        "slug": "modi-garba-2023",
        "name": "PM Modi 'Deepfake' Garba Video",
        "occurred_on": date(2023, 11, 17),
        "location": "Nationwide",
        "platform": "Instagram / X",
        "deaths": 0,
        "harm_type": "ELECTORAL",
        "verdict": "MISLEADING",
        "claim": "A video shows PM Narendra Modi performing garba at a festival.",
        "summary": (
            "A video of a man resembling PM Narendra Modi dancing garba went viral. The PM cited it "
            "publicly as a dangerous deepfake, showing how hard it has become to tell synthetic media "
            "from authentic footage."
        ),
        "what_was_true": (
            "The man was a lookalike, Vikas Mahante. The footage was real, not AI-generated, and did "
            "not show the Prime Minister."
        ),
        "forward_text": "PM Modi dancing garba with women at the festival! Look at this video 😍",
        "fact_check_days": None,
        "reference_query": "Vikas Mahante",
    },
]

KNOWN_PATTERNS = [
    {
        "slug": "child-lifter-rumour",
        "name": "Child-lifter / organ-theft gang rumour",
        "category": "VIOLENCE",
        "typical_verdict": "FALSE",
        "description": "Warnings of kidnapping or organ-harvesting gangs in disguise; repeatedly linked to mob lynchings.",
        "example_text": "Child kidnapping gang has entered the area disguised as beggars and sadhus, they remove kidneys, stay alert and forward",
        "keywords": ["kidnap", "child lifter", "bachcha chor", "organ", "kidney", "gang", "disguised", "beggars"],
    },
    {
        "slug": "miracle-cure",
        "name": "Miracle home-remedy cure",
        "category": "HEALTH",
        "typical_verdict": "FALSE",
        "description": "Claims that a household item (cow urine, garlic, hot water, lemon) cures a serious disease.",
        "example_text": "Drinking cow urine, hot water with lemon or eating garlic cures corona virus completely doctors confirm",
        "keywords": ["cure", "cures", "gaumutra", "cow urine", "garlic", "hot water", "lemon", "home remedy", "corona", "cancer"],
    },
    {
        "slug": "old-video-new-context",
        "name": "Old or foreign footage in a new context",
        "category": "COMMUNAL",
        "typical_verdict": "FALSE",
        "description": "Real but unrelated video or photo re-captioned as a current local event.",
        "example_text": "Watch this video of what happened today in our city, they attacked our people, share before it is deleted",
        "keywords": ["watch this video", "happened today", "before it is deleted", "share before", "our people", "attacked"],
    },
    {
        "slug": "fake-government-scheme",
        "name": "Fake government scheme or giveaway",
        "category": "FINANCIAL",
        "typical_verdict": "FALSE",
        "description": "Free recharge, laptops or cash under a government scheme, usually with a phishing link.",
        "example_text": "Government is giving free laptop and 3 months free recharge to all students, register on this link before last date",
        "keywords": ["free recharge", "free laptop", "yojana", "register now", "last date", "click link", "government is giving"],
    },
    {
        "slug": "currency-hoax",
        "name": "Currency / banking hoax",
        "category": "FINANCIAL",
        "typical_verdict": "FALSE",
        "description": "GPS chips in banknotes, coins being withdrawn, or bank accounts being frozen.",
        "example_text": "New 2000 rupee note has a GPS nano chip, RBI will ban 10 rupee coins from tomorrow",
        "keywords": ["rbi", "nano chip", "gps chip", "note ban", "coins invalid", "bank closed", "rupee note"],
    },
    {
        "slug": "evm-tampering",
        "name": "Election / EVM tampering claim",
        "category": "ELECTORAL",
        "typical_verdict": "UNVERIFIED",
        "description": "Unsubstantiated claims of hacked voting machines or changed voting dates.",
        "example_text": "EVM machines are hacked, every vote goes to one party, voting date changed for your area",
        "keywords": ["evm", "hacked", "voting date", "election commission", "vote goes", "rigged"],
    },
    {
        "slug": "fake-who-advisory",
        "name": "Fake WHO / ministry advisory",
        "category": "HEALTH",
        "typical_verdict": "FALSE",
        "description": "Fabricated circulars attributed to WHO, ICMR or a ministry.",
        "example_text": "WHO has announced new guidelines, ICMR circular says all shops will be closed, forward this official message",
        "keywords": ["who", "icmr", "ministry", "circular", "official message", "guidelines", "announced"],
    },
    {
        "slug": "vaccine-conspiracy",
        "name": "Vaccine conspiracy",
        "category": "HEALTH",
        "typical_verdict": "FALSE",
        "description": "Vaccines cause infertility, contain microchips or alter DNA.",
        "example_text": "Vaccine contains microchip and causes infertility, it changes your DNA, do not take it",
        "keywords": ["vaccine", "microchip", "infertility", "dna", "magnet", "5g"],
    },
    {
        "slug": "communal-conspiracy",
        "name": "Communal conspiracy narrative",
        "category": "COMMUNAL",
        "typical_verdict": "FALSE",
        "description": "Claims that a community is deliberately poisoning, spitting on or contaminating goods.",
        "example_text": "They are spitting on fruits and vegetables to spread disease, boycott their shops, forward to save your family",
        "keywords": ["spitting", "boycott", "jihad", "poisoning", "their shops", "save your family"],
    },
    {
        "slug": "deepfake-political",
        "name": "Synthetic or lookalike political video",
        "category": "ELECTORAL",
        "typical_verdict": "MISLEADING",
        "description": "Edited, AI-generated or lookalike footage of a political leader.",
        "example_text": "Viral video shows the Prime Minister dancing, saying something shocking, watch the leader's real face",
        "keywords": ["deepfake", "pm modi", "prime minister", "minister", "leader", "viral video", "ai video"],
    },
]


def _seed_claim(inc: dict) -> Claim:
    when = datetime.combine(inc["occurred_on"], time(12, 0), tzinfo=timezone.utc)
    return Claim(
        id=f"seed{inc['slug'].replace('-', '')}"[:32],
        created_at=when,
        completed_at=when,
        input_type="text",
        raw_input=inc["forward_text"],
        input_hash=input_hash(inc["forward_text"]),
        platform=inc["platform"].split(" / ")[0].lower(),
        status="complete",
        is_seed=True,
        claim_text=inc["claim"],
        language="en",
        language_name="English",
        claim_type=inc["harm_type"],
        urgency="CRITICAL" if inc["deaths"] else "HIGH",
        verdict=inc["verdict"],
        confidence=None,
        summary=f"{inc['summary']} {inc['what_was_true']}",
        reasoning_chain=[],
        myth=inc["claim"],
        fact=inc["what_was_true"],
        fact_source="Documented incident archive",
        harm_type=inc["harm_type"],
        harm_level="CRITICAL" if inc["deaths"] else "HIGH",
        harm_score=10.0 if inc["deaths"] else 7.0,
        harm_rationale=f"Archived incident: {inc['name']} ({inc['deaths']} deaths).",
        agent_log=[],
    )


async def seed(session: AsyncSession) -> None:
    existing_incidents = set((await session.scalars(select(Incident.slug))).all())
    existing_patterns = set((await session.scalars(select(KnownPattern.slug))).all())
    existing_claims = set((await session.scalars(select(Claim.id).where(Claim.is_seed.is_(True)))).all())

    added = 0
    for inc in INCIDENTS:
        if inc["slug"] not in existing_incidents:
            session.add(
                Incident(
                    slug=inc["slug"],
                    name=inc["name"],
                    occurred_on=inc["occurred_on"],
                    location=inc["location"],
                    platform=inc["platform"],
                    deaths=inc["deaths"],
                    harm_type=inc["harm_type"],
                    verdict=inc["verdict"],
                    summary=inc["summary"],
                    what_was_true=inc["what_was_true"],
                    forward_text=inc["forward_text"],
                    forward_is_reconstruction=True,
                    spread_minutes=None,
                    fact_check_days=inc["fact_check_days"],
                    reference_query=inc["reference_query"],
                )
            )
            added += 1
        claim = _seed_claim(inc)
        if claim.id not in existing_claims:
            session.add(claim)
            added += 1

    for pat in KNOWN_PATTERNS:
        if pat["slug"] not in existing_patterns:
            session.add(KnownPattern(**pat))
            added += 1

    if added:
        await session.commit()
        logger.info(f"Seeded {added} rows")
