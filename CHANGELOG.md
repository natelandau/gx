## v0.7.1 (2026-05-12)

### Fix

- support nclutils >= v3.0.0 (#17)

### Refactor

- delegate subprocess and gh wrappers to nclutils (#18)

## v0.7.0 (2026-05-04)

### Feat

- **feat**: add --local flag to branch from local default (#14)

### Fix

- **console**: use nllog console
- **feat**: pass --no-track when branching from remote refs (#16)

### Refactor

- replace lib/console with nllog package (#15)

## v0.6.0 (2026-05-03)

### Feat

- **done**: verify branch is merged before deleting (#12)
- **done**: hint at gx clean when run on default branch

### Fix

- **feat**: branch from origin/<default> instead of stale local ref (#11)

### Refactor

- extract pull's git-flow helpers into lib/ (#13)

## v0.5.0 (2026-03-23)

### Feat

- **log**: add inline ref badges to log output

### Refactor

- extract panel and analyzer classes into lib/ (#7)

## v0.4.0 (2026-03-22)

### Feat

- **info**: add repository dashboard command (#5)

## v0.3.0 (2026-03-22)

### Feat

- **console**: redesign CLI output with spinners and panels (#4)
- **log**: add pretty log command (#3)

## v0.2.0 (2026-03-21)

### Feat

- **cli**: add --version/-V flag to root command (#2)
- add initial feature set
