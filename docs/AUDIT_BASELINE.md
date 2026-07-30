# Audit baseline

Baseline was recorded from the original `masood1996-geo/ai-scraper` `main` branch
before Prime changes.

| Item | Baseline |
| --- | --- |
| Working tree | `ai_scraper/llm.py` modified by the user; preserved in Prime |
| Python | 3.13.14 locally; project declared 3.10+ |
| Package manager/build | pip + setuptools |
| Tests | `pytest`: no tests collected |
| Lint | Ruff: 17 errors |
| Formatting | Black not installed |
| Type checking | No configured type checker |
| Build | Failed because `build` was not installed |
| CI | No `.github` directory |
| License | MIT in `LICENSE` and package metadata |
| Repository visibility | Public before the requested split |

## Confirmed issue classification

| ID | Baseline status | Root cause |
| --- | --- | --- |
| AS-01 | Confirmed | command safety existed but no command surface called it |
| AS-02 | Confirmed | missing recovery handlers returned success |
| AS-03 | Confirmed | wait/content context writes were not consumed by retries |
| AS-04 | Confirmed | `save_cleaning_rule` had no application write path |
| AS-05 | Confirmed | prompt text was saved before candidate improvement was tested |
| AS-06 | Confirmed | one heuristic score was described too broadly |
| AS-07 | Confirmed | English exception-message matching and timeout default |
| AS-08 | Confirmed | no tests |
| AS-09 | Confirmed | no CI or quality configuration |
| AS-10 | Confirmed | README overclaimed learning, recovery, safety, and relationship |
| CR-01 | Confirmed | README claimed OpenHouse usage without a dependency |
| CR-04 | Partial | source comments referenced adapted patterns without one attribution document |
| CR-05 | Confirmed | installers created a predictable administrator credential |

The original repository was made private before the new public Prime repository was
created. Prime work occurred in an isolated checkout, so the original uncommitted
user change remained untouched.
