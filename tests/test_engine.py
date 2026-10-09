import json

from PIL import Image

from app.config import Settings
from app.engine import Engine


def test_report_and_csv_use_real_coordinates(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 100)).save(source)

    class EngineWithDetections(Engine):
        def predict(self, image, confidence, preset):
            import numpy as np

            return np.asarray(image), [dict(class_id=0, label="person", confidence=0.91, box=[1, 2, 30, 40])]

    engine = EngineWithDetections(Settings(data_dir=tmp_path))
    result = engine.run(
        dict(id="test", kind="image", confidence=0.35, preset="all"), source, tmp_path, lambda _: None
    )
    assert result["counts"] == {"person": 1}
    assert "detections" not in result
    assert "0,person,0.91,1,2,30,40" in (tmp_path / "detections.csv").read_text(encoding="utf-8-sig")
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["detections"][0]["box"] == [
        1,
        2,
        30,
        40,
    ]
    assert (tmp_path / "annotated.jpg").is_file()
