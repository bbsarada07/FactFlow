"""Seed documented incidents, their archived verdicts, and known misinformation patterns.

Every figure shown for an incident (date, deaths, what was true) is taken from the
linked source, which was retrieved and read when this file was written (October 2026).
The forward texts are representative reconstructions of the rumours as reported,
not verbatim copies; the UI labels them as such. Seeding is an upsert, so edits here
propagate to existing databases on the next start.
"""
from datetime import datetime, time, timezone, date

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Claim, Incident, KnownPattern, Source, new_slug
from services.text_utils import input_hash, normalize

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
        "claim": "A gang of child thieves harvesting organs is active in the area.",
        "summary": (
            "A rumour spread through the village on WhatsApp that a gang of child thieves harvesting "
            "organs was active in the area. A vigilante group lynched two Hindu sadhus and their driver."
        ),
        "what_was_true": "The victims were two sadhus and their driver, not child thieves or organ harvesters.",
        "forward_text": (
            "ALERT!! Gangs of child kidnappers are moving in villages at night dressed as sadhus and "
            "police. They take children and remove their kidneys. Stay awake, guard your village and "
            "stop every outside vehicle. Forward to all groups!"
        ),
        "reference_query": "2020 Palghar mob lynching",
        "source_url": "https://en.wikipedia.org/wiki/2020_Palghar_mob_lynching",
        "source_label": "Wikipedia: 2020 Palghar mob lynching",
        "extra_sources": [],
    },
    {
        "slug": "muzaffarnagar-2013",
        "name": "Muzaffarnagar Riots",
        "occurred_on": date(2013, 8, 27),
        "location": "Muzaffarnagar, Uttar Pradesh",
        "platform": "Social media",
        "deaths": 62,
        "harm_type": "COMMUNAL",
        "verdict": "FALSE",
        "claim": "A video shows the murder of two young men from Kawal village.",
        "summary": (
            "A video said to show the killing of two cousins from Kawal village circulated during rising "
            "tension. In the riots that followed (27 August to 17 September 2013), 62 people died."
        ),
        "what_was_true": "The video was footage of unrelated violence in Pakistan from several years earlier.",
        "forward_text": (
            "Watch how they killed our boys in Kawal. Share this video so everyone sees what was done "
            "to them. Don't stay silent!"
        ),
        "reference_query": "2013 Muzaffarnagar riots",
        "source_url": "https://en.wikipedia.org/wiki/2013_Muzaffarnagar_riots",
        "source_label": "Wikipedia: 2013 Muzaffarnagar riots",
        "extra_sources": [],
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
        "claim": "A child-kidnapping gang has entered the district.",
        "summary": (
            "WhatsApp messages about child kidnappers had spread widely in the area. Five men who got off a "
            "bus at the Sunday market were dragged to the gram panchayat office and beaten to death."
        ),
        "what_was_true": (
            "There was no kidnapping gang. The victims were members of a nomadic community who had come "
            "to the weekly market to seek alms."
        ),
        "forward_text": (
            "Child kidnapping gang has entered our district. Many members, dressed as beggars. They "
            "kidnap children and sell their organs. Share in all groups and stay alert!"
        ),
        "reference_query": "Dhule Rainpada lynching July 2018",
        "source_url": "https://www.boomlive.in/dhule-lynching-takes-death-toll-due-to-fake-news-to-23-5-things-to-know",
        "source_label": "BOOM",
        "extra_sources": [
            {"label": "The Quint", "url": "https://www.thequint.com/news/india/lynchings-due-to-rumours-spreading-on-whatsapp"}
        ],
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
            "During the pandemic, videos were shared with communal captions claiming Muslims were "
            "spitting on food to spread the coronavirus."
        ),
        "what_was_true": (
            "Fact-checkers traced the videos to earlier years, other countries or unrelated events; "
            "none showed deliberate spreading of COVID-19."
        ),
        "forward_text": (
            "SHOCKING video: see how they are spitting on fruits to spread corona. Don't buy from them. "
            "Forward to save your family."
        ),
        "reference_query": "fact check video spitting on food coronavirus India",
        "source_url": "https://www.altnews.in/old-video-falsely-viral-as-muslim-man-spitting-on-food-at-indian-restaurant-in-the-backdrop-of-coronavirus-pandemic/",
        "source_label": "Alt News",
        "extra_sources": [
            {"label": "BOOM", "url": "https://www.boomlive.in/fake-news/false-video-shows-muslim-man-spitting-on-bread-to-spread-coronavirus-7572"}
        ],
    },
    {
        "slug": "manipur-2023",
        "name": "Manipur Fake Photo",
        "occurred_on": date(2023, 5, 4),
        "location": "B. Phainom, Kangpokpi, Manipur",
        "platform": "Social media",
        "deaths": 2,
        "harm_type": "COMMUNAL",
        "verdict": "FALSE",
        "claim": "A photo shows a Meitei woman raped and murdered by Kuki men in Manipur.",
        "summary": (
            "As ethnic violence broke out, a photo of a woman's body wrapped in plastic was shared as a "
            "Meitei woman killed in Manipur. Sources cited by India Today said fake rape news triggered the "
            "4 May mob attack in B. Phainom, where a CBI chargesheet says two family members of one of the "
            "assaulted women were killed."
        ),
        "what_was_true": "The photo was from an unrelated 2022 murder case outside Manipur.",
        "forward_text": (
            "Our sister was raped and killed in Churachandpur. Look at what they did to her body. "
            "We cannot keep quiet any more. Share widely."
        ),
        "reference_query": "Manipur fake photo Meitei woman fact check",
        "source_url": "https://www.boomlive.in/fact-check/viral-photo-kuki-people-rape-kill-meitei-woman-old-picture-aayushi-murder-case-social-media-21874",
        "source_label": "BOOM",
        "extra_sources": [
            {"label": "Business Today", "url": "https://businesstoday.in/latest/story/manipur-shocker-fake-rape-news-triggered-mob-to-parade-women-naked-say-sources-390666-2023-07-20"},
            {"label": "Deccan Herald (CBI chargesheet)", "url": "https://www.deccanherald.com/india/manipur/cbi-files-charge-sheet-in-case-related-to-naked-parading-of-tribal-women-in-manipur-2729041"},
        ],
    },
    {
        "slug": "modi-garba-2023",
        "name": "PM Modi 'Deepfake' Garba Video",
        "occurred_on": date(2023, 11, 11),
        "location": "Nationwide",
        "platform": "Instagram / X",
        "deaths": 0,
        "harm_type": "ELECTORAL",
        "verdict": "MISLEADING",
        "claim": "A video shows PM Narendra Modi performing garba.",
        "summary": (
            "A video of a man resembling PM Narendra Modi dancing garba went viral and was widely "
            "described as a deepfake."
        ),
        "what_was_true": (
            "The man was a lookalike, Vikas Mahante, filmed at a Diwali event in London. The footage was "
            "real, not AI-generated, and did not show the Prime Minister."
        ),
        "forward_text": "PM Modi dancing garba with women at the festival! Look at this video 😍",
        "reference_query": "Modi garba video lookalike Vikas Mahante fact check",
        "source_url": "https://www.boomlive.in/fact-check/narendra-modi-doing-garba-lookalike-vikas-mahante-fact-check-23560",
        "source_label": "BOOM",
        "extra_sources": [
            {"label": "Alt News", "url": "https://www.altnews.in/no-man-performing-garba-in-viral-video-is-not-pm-narendra-modi/"}
        ],
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



INCIDENT_FIELDS = (
    "name", "occurred_on", "location", "platform", "deaths", "harm_type", "verdict", "summary",
    "what_was_true", "forward_text", "reference_query", "source_url", "source_label", "extra_sources",
)


def _apply_seed_claim(claim: Claim, inc: dict) -> None:
    """Copy an incident's archived verdict onto its seed claim (used for insert and update)."""
    when = datetime.combine(inc["occurred_on"], time(12, 0), tzinfo=timezone.utc)
    claim.created_at = when
    claim.completed_at = when
    claim.input_type = "text"
    claim.raw_input = inc["forward_text"]
    claim.input_hash = input_hash(inc["forward_text"])
    claim.normalized_text = normalize(inc["forward_text"])
    claim.platform = inc["platform"].split(" / ")[0].lower()
    claim.status = "complete"
    claim.is_seed = True
    claim.is_public = True
    claim.claim_text = inc["claim"]
    claim.language = "en"
    claim.language_name = "English"
    claim.claim_type = inc["harm_type"]
    claim.urgency = "CRITICAL" if inc["deaths"] else "HIGH"
    claim.verdict = inc["verdict"]
    claim.model_verdict = None
    claim.confidence = None
    claim.confidence_band = None
    claim.summary = f"{inc['summary']} {inc['what_was_true']}"
    claim.reasoning_chain = []
    claim.evidence_gaps = []
    claim.checks_to_do = []
    claim.myth = inc["claim"]
    claim.fact = inc["what_was_true"]
    claim.fact_source = inc["source_label"]
    claim.correction = None
    claim.harm_type = inc["harm_type"]
    claim.harm_level = "CRITICAL" if inc["deaths"] else "HIGH"
    claim.harm_score = None
    claim.harm_rationale = f"Archived incident: {inc['name']}."
    claim.agent_log = []


async def seed(session: AsyncSession) -> None:
    """Upsert incidents, their archive claims (with their real source) and known patterns."""
    incidents = {i.slug: i for i in (await session.scalars(select(Incident))).all()}
    patterns = set((await session.scalars(select(KnownPattern.slug))).all())
    claims = {c.id: c for c in (await session.scalars(select(Claim).where(Claim.is_seed.is_(True)))).all()}

    for inc in INCIDENTS:
        row = incidents.get(inc["slug"])
        if row is None:
            row = Incident(slug=inc["slug"], forward_is_reconstruction=True)
            session.add(row)
        for f in INCIDENT_FIELDS:
            setattr(row, f, inc[f])
        row.source_confirmed = True
        row.fact_check_days = None
        row.spread_minutes = None

        claim_id = f"seed{inc['slug'].replace('-', '')}"[:32]
        claim = claims.get(claim_id)
        if claim is None:
            claim = Claim(id=claim_id, slug=new_slug(), sources=[])
            session.add(claim)
        _apply_seed_claim(claim, inc)
        await session.flush()
        if not any(s.url == inc["source_url"] for s in claim.sources):
            claim.sources.append(
                Source(
                    name=inc["source_label"],
                    url=inc["source_url"],
                    title=inc["name"],
                    snippet=inc["what_was_true"],
                    origin="archive",
                    tier=1,
                    credibility=0.9,
                    stance="REFUTES",
                )
            )

    for pat in KNOWN_PATTERNS:
        if pat["slug"] not in patterns:
            session.add(KnownPattern(**pat))

    await session.commit()
    logger.info(f"Seed data up to date ({len(INCIDENTS)} incidents, {len(KNOWN_PATTERNS)} patterns)")
