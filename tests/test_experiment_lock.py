import pytest

from scripts import run_experiments


@pytest.mark.parametrize(
    ("final", "regen", "message"),
    [
        (True, False, "Refusing to evaluate again"),
        (False, True, "Refusing to regenerate its data"),
    ],
)
def test_final_test_lock_protects_test_data(tmp_path, monkeypatch, final, regen, message):
    lock = tmp_path / "test_eval.lock"
    lock.write_text("test evaluated\n")
    monkeypatch.setattr(run_experiments, "LOCK", lock)

    with pytest.raises(SystemExit, match=message):
        run_experiments.main(final=final, regen=regen)
