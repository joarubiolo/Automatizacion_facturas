from paddleocr import PaddleOCR

PaddleOCR(
    lang="es",
    device="cpu",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    text_detection_model_name="PP-OCRv5_mobile_det",
    text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
    text_recognition_batch_size=1,
    text_det_limit_side_len=1600,
    text_det_limit_type="max",
)

print("Modelos PaddleOCR descargados y listos.")
