# Test Evolution Log

Tests for the `EvolutionLog` module (`evolution.log`), covering:

- **test_init_creates_dir**: Verifies that an `EvolutionLog` instance is initialized with the correct root path.
- **test_win_log**: Ensures `log.win()` returns a record with outcome `"win"`.
- **test_improvement**: Ensures `log.improvement()` returns a record with the correct action string.
- **test_stats**: Verifies that `log.stats()` returns a dictionary with a `total_events` key after logging wins and losses.
