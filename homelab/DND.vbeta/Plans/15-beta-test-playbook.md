---
plan: 15
title: Beta test playbook
stage: 4
model: peter
mode: n/a
depends_on: [14]
inputs: [local beta build, first campaign, friends]
outputs: [local-beta exit checklist, friends-session checklist, feedback form/template, bug triage list, ship criteria]
done_when: [local beta checklist passes on Peter's machine, one full friends session completed with feedback captured, ship criteria agreed]
status: stub
---

# 15: Beta test playbook

## Goal
Sequence from D19: local beta first, friends test when it is solid, then complete and ship.
This plan is Peter's: it is checklists and criteria, not code.

## Local beta exit checklist (draft)
- Two local clients over Relay complete a full session of the first campaign.
- Auto-DM completes the same campaign solo.
- Save/load mid-combat works. Reconnect works.
- No rules rejection without a visible reason. No engine exception in a 2-hour session.

## Friends session checklist (draft)
- Install notes tested by one friend beforehand.
- Discord voice set up; join code shared at start.
- Feedback captured per feature: look, clarity of rules, pacing, bugs.

## Ship criteria
Agreed after the friends session, appended to DECISIONS.md.
