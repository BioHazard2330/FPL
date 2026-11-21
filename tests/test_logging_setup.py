import logging

from fpl_agent.logging_setup import SharedRotatingFileHandler


def test_rollover_while_another_process_holds_the_file(tmp_path):
    path = tmp_path / "x.log"
    other = open(path, "a", encoding="utf-8")
    handler = SharedRotatingFileHandler(path, maxBytes=300, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    errors = []
    handler.handleError = lambda record: errors.append(record)
    log = logging.getLogger("test_shared_rotation")
    log.propagate = False
    log.addHandler(handler)
    try:
        for i in range(40):
            log.warning("line %03d %s", i, "x" * 20)
        other.write("from the other process\n")
        other.flush()
    finally:
        log.removeHandler(handler)
        handler.close()
        other.close()
    assert errors == []
    assert (tmp_path / "x.log.1").exists()
    assert path.stat().st_size < 600
    assert "line 039" in path.read_text(encoding="utf-8")
