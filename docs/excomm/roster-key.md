# ExComm roster key — maintainers only

This file maps each `member_id` in `data/excomm/registry.yaml` to the 1962 figure its
disposition and belief system are drawn from. **It is documentation. No code reads it, and
no real name from the right-hand column may appear in `data/excomm/registry.yaml` or in any
prompt** — `tests/test_excomm.py` and `tests/test_access_matrix.py` enforce that.

The roster is *1962-shaped*, not nominal: prompts carry the institutional seat and an
anonymised behavioural profile, never a name, for the same anti-leakage reason the scenario
is "Nation A / Nation B" and not "Cuba". See ADR 0008.

| `member_id` | 1962 seat | Figure the profile draws on | Belief system drawn from |
|---|---|---|---|
| `defense_secretary` | Secretary of Defense | Robert McNamara | memoirs and lectures on the management of force; the limits of systems analysis in strategy |
| `state_secretary` | Secretary of State | Dean Rusk | diplomatic correspondence; later writing on alliance management and coercive diplomacy |
| `attorney_general` | Attorney General | Robert F. Kennedy | *Thirteen Days*; later speeches on the ethics of state violence |
| `national_security_advisor` | National Security Advisor | McGeorge Bundy | academic writing on decision-making; later reflections on the crisis |
| `deputy_state_secretary` | Under Secretary of State | George Ball | internal memoranda against a surprise strike; later writing on constraints on force |
| `jcs_chairman` | Chairman, Joint Chiefs of Staff | Maxwell Taylor | *The Uncertain Trumpet* and professional writing on limited war and flexible response |
| `dci` | Director of Central Intelligence | John McCone | declassified assessments; later testimony on reading strategic indicators |
| `treasury_secretary` | Secretary of the Treasury | C. Douglas Dillon | public statements and later writing on economic policy and the domestic politics of national security |
| `soviet_affairs_adviser` | Adviser on Soviet affairs / former Ambassador to Moscow | Llewellyn Thompson | diplomatic cables; later writing on Soviet decision-making and crisis behaviour |
| `presidential_counsel` | Special Counsel to the President | Theodore Sorensen | speech drafts; *Kennedy* and later memoir material |
| `vice_president` | Vice President | Lyndon B. Johnson | public remarks; a later inside account of the administration |

## Editing the profiles

`disposition` and `beliefs` are prose you can revise directly. Keep them:

- **anonymised** — institutional role and temperament, never a name, never a dated episode;
- **general** — a belief is a standing principle ("force is only strategy when it serves a
  political objective"), not a dated statement ("on 18 October he said…");
- **nuanced** — a temperament and how it moves under pressure, not a one-word caricature.

Adding a member is `+deliberation_max_rounds` model calls per replication on the
`excomm_debate` arm — see the cost note in ADR 0008.
