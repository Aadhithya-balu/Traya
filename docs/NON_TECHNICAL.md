# TRAYA in Plain Language

[docs/README.md](README.md) · For project reviewers, faculty, judges and
non-technical stakeholders. **No programming terminology.** The technical
version is in [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md); the current
state of the build is in [AUDIT.md](AUDIT.md).

If you only read one page before asking a question, read this one, then
[Limitations](#what-traya-cannot-do), which is the shortest honest answer to the
question people actually ask.

## The problem

Someone has an accident. They are unconscious, or too shaken to say who they
are, or they cannot speak the language of the people around them.

The first hour after a road accident is when medical treatment matters most. In
that hour, a person's identity is often the one piece of information that is
missing and hardest to get.

Right now, people solve this with whatever is in their pocket. A wallet. A phone
lock screen photo. A pass. If none of those are on them, responders have nothing
- and they spend valuable minutes looking for a phone number in a bag instead of
starting treatment.

There is a specific moment where this goes wrong. **A person is unidentified,
surrounded by people who want to help, and every helpful person is waiting for
someone else to act first.** The information exists somewhere. It just cannot
reach the person who needs it, at the time they need it.

## Who experiences it

- **The person who cannot speak.** Unconscious, injured, confused, or simply not
  able to communicate in the language being spoken around them.
- **The bystander who wants to help.** Standing there with a phone, willing,
  and not knowing what to do next.
- **The responder.** Who needs the name, the medical information and the family
  contact, and needs them in that order, quickly.
- **The family.** Who do not yet know, and who will be contacted once someone
  finds out.

## What exists today, and the gap

Helpful things already exist:

- **Emergency ID cards and bracelets.** They work, and millions wear them. They
  depend on the person having one, having it on them, and it being found.
- **Phone lock-screen medical information.** Useful, and depends on the phone
  being unlocked or the info being visible to a stranger.
- **Searchable ID numbers and QR tags.** Useful, and depend on the same
  conditions.
- **Good identification systems at hospitals.** They work well, and they work
  once the person has arrived.

The gap is common to all of them: **every one requires something physical on the
person, or someone to already know who they are.**

When a person is injured, they are not carrying their wallet. Their phone may be
locked, or damaged, or in a pocket nobody wants to search in a crowd. The
information may be exactly where it is always kept and exactly where it is least
useful.

## What TRAYA is

TRAYA lets an authorised person use an ordinary phone camera to identify an
unconscious person at the scene.

The idea is short:

1. Open TRAYA and press the emergency button.
2. Point the phone at the person's face.
3. TRAYA looks up whether that face is someone who has registered in advance.
4. If it finds them, it shows the information a responder in that role is
   allowed to see - medical alerts, emergency contacts, and what to do.
5. It records what happened, so there is a clear record of the incident.

No special equipment. **A phone, or any laptop with a webcam.** No card readers,
no scanners, no dedicated hardware of any kind. That constraint is the point:
the things that are already in people's pockets, or already in the responder's
pocket, are the only tools this can depend on.

### Why zero hardware matters

Every solution that needs a special device has the same weakness. It only works
when that device is present, charged, in someone's hand, and used correctly at
the exact moment it is needed.

A phone is already there, because the person took a photo of the accident. The
only assumption TRAYA makes is the one that is already true: **someone has a
camera and is willing to point it at the person who needs help.** That is a low
bar, and lowering it is most of the value.

## How it works

Nothing magic happens, and it is worth being precise about it.

**Before the emergency.** A person registers in advance. They enter their
emergency medical information - blood group, allergies, critical conditions,
medications - and the names and numbers of people to contact. Then they register
their face, by following on-screen instructions that ask for a few photos from
slightly different angles. The app checks each photo is usable and tells them if
it is not. This takes a few minutes, once, in advance.

**During the emergency.** The camera finds a face in the picture and checks the
picture is good enough to be fair to the person in it - not too dark, not too
blurry, not too far away, not blocked. It then compares the face against the
registered ones and reports what it finds.

**What it reports, and how carefully.** This is the most important part of the
whole design:

> **TRAYA does not say "this is definitely that person."** It says "this may be
> that person, please check."

If the result is uncertain, it says so and shows the shortlist for a human to
decide. If the picture is too poor, it says which problem it is and how to fix
it. **If it is not confident, it does not guess.** A wrong identification in an
emergency sends an ambulance to the wrong history or calls the wrong family, so
being unsure and admitting it is the correct behaviour, not a failure.

**Afterwards.** The incident is recorded: when, where, what was found, how
certain the system was, and what was done. Not so anyone can be spied on - so
that there is an honest account, and so the system can be checked later.

## What happens when it does not work

This matters more than when it works, so it is designed rather than hoped for.

The face may be obscured by injury, bandages or hands. The lighting may be bad.
The camera may be poor. The person may not have registered. The angle may be
badly wrong. The system may simply not be sure.

In every one of those cases TRAYA still helps. It moves to **fallback
identification**: a responder confirms the identity directly, records what they
found, and the medical information and contacts still reach them. The incident
is still logged.

**A fallback is a normal outcome with a full record - not a dead end and not a
failure.** And critically, there is no offline mode. If the service is
unreachable, TRAYA says so plainly rather than pretending to work.

## How privacy is handled

Emergency identification is a genuinely sensitive problem, and the honest answer
is that it cannot be made risk-free. What can be done is make it proportionate.

- **You register in advance, and you can withdraw.** Consent is a real recorded
  decision, not a checkbox you click once. You can withdraw, and withdrawal is
  recorded rather than erased.
- **Face data is sensitive and permanently so.** A password can be changed. A
  face cannot. TRAYA treats the stored face information as the most sensitive
  thing it holds: encrypted, never sent to your browser, never written into
  logs, and readable only by the system itself.
- **Not everyone sees everything.** A police officer and a doctor need different
  information. Police get identity and contacts. Doctors get the medical detail.
  **Neither gets the other's.** A bystander gets the bare minimum - enough to
  help.
- **Every access is recorded.** When somebody looks at a person's medical
  information, that is written down. It cannot be done invisibly.
- **Being looked up is limited.** Looking up faces repeatedly is restricted and
  recorded, so nobody can quietly use it to discover who has registered.
- **Nobody receives face data in bulk.** There is no way to export the
  collection. One request matches one face; there is no "give me everyone".

## What is honest about the limits

The most useful thing on this page.

**The recognition technology is not finished.** This is the single most
important caveat, and it is not buried. The system demonstrates the complete
process - camera, quality checks, matching, threshold decision, emergency
information, incident record - end to end, so it can be understood and tested.

**As of Phase 5 there is real face recognition in it.** A genuine face detector
and a genuine 128-number face description are now installed and run when their
model files are present. On three test photographs it told two people apart with
a wide margin.

**That is as far as the evidence goes, and the distinction matters.** Three
photographs cannot tell you how often the system would be wrong about a real
person, which is the only question that matters in an emergency. The
confidence thresholds that decide "match" versus "check with a human" are
inherited from the old placeholder and have not been re-measured for the new
recogniser. **The system must not be used to identify a real person.**

The system labels which engine produced every result, and it is never ambiguous:
you cannot mistake the placeholder for the real one, and you cannot mistake a
real-but-uncalibrated match for a validated one. Re-measuring the thresholds on
a proper test set is a later phase, and when those numbers exist they will be
published in full - including any that look bad.

**Other limits, stated plainly:**

- **Not a replacement for emergency services.** TRAYA supports a response. It
  is not a response.
- **Not diagnosis.** It displays what a person registered. It does not assess
  them.
- **Only helps if you registered.** A person who never registered cannot be
  identified. The fallback exists for exactly this.
- **Enrolment is self-selected.** The registered population is not a
  representative one, which is a well-known and unsolved fairness problem in
  every identity system.
- **A database is a database.** Even with encryption and access control, a
  serious breach at the hosting provider exposes the emergency medical records
  of everyone registered.
- **Field trials have not happened.** Everything so far is lab and simulated
  conditions. Real ambulance conditions - noise, movement, bystanders, shouted
  instructions, gloves - are a different environment and the numbers will be
  worse.

## What TRAYA is not claiming

Being clear about this is part of the point.

TRAYA is **not** claiming to be the first application of this kind. Emergency ID
cards, medical bracelets, lock-screen medical info and face recognition all
exist and have for years. Other emergency identification research exists.

What TRAYA is claiming is a specific **combination**, which is where a product
gap analysis should later look:

- Works on an **ordinary phone**, with no dedicated hardware
- **Mobile-first** emergency workflow, designed for one-handed use under stress
- **Biometric matching combined with a role-filtered emergency profile**
- **Explicit fallback** when recognition does not work
- **Role-based access** enforced at the data, not just in the interface
- **Two languages**, including Tamil, designed for non-technical users
- **Accessibility** and honest uncertainty as core requirements

Whether that combination is genuinely novel is exactly what a formal prior-art
and product-gap analysis should establish. **This project does not assert it.**

## Who this is for

- **A bystander.** No account needed for the emergency flow. Press the button,
  follow the prompts, do what the screen says next.
- **A responder.** More detail, filtered to your role, and an incident record.
- **A family member.** Register once, so that a bad day does not become an
  unidentifiable one.
- **An administrator.** Oversight, audit, and accountability.

## Where it goes next

In rough order of how much they matter:

1. **A real recogniser**, measured honestly, with published numbers including
   the ones that are unflattering.
2. **A real deployment** - one that runs properly rather than falling back to a
   local file when the network drops.
3. **Privacy enforced at the database**, so that security is not a promise in
   the interface code.
4. **Field trials** with actual responders, which is the only thing that
   produces evidence about whether this helps.
5. **More languages**, with community involvement rather than machine
   translation.
6. **Wider evaluation** across age, skin tone, disability and camera quality -
   the fairness question that every identity system has to answer and most avoid.

## The one-sentence version

> In the first hour of an emergency, a person's identity is often the missing
> piece of information that matters most. TRAYA tries to close that gap using
> the camera on a phone that is already in the room, tells you how sure it is,
> has a fallback when it is not sure, and records what happened so the response
> can be honest.

**And the caveat that goes with it:** the process works end to end today. The
face recognition inside it does not yet, and this project will not describe it
as if it did.