FROM python:3.12-slim

# The face models (see README). Downloaded at build time, checked against known hashes.
ADD --checksum=sha256:8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4 \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
    /models/face_detection_yunet_2023mar.onnx
ADD --checksum=sha256:0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79 \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx \
    /models/face_recognition_sface_2021dec.onnx
ADD --checksum=sha256:4daa100034482525a26c9afb9297c16580a531189e66e3d2b2ac7d32becfd593 \
    https://storage.openvinotoolkit.org/repositories/open_model_zoo/public/2022.1/open-closed-eye-0001/open_closed_eye.onnx \
    /models/open_closed_eye.onnx
RUN chmod 644 /models/*.onnx

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FACES_MODELS_DIR=/models
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
USER nobody
EXPOSE 3400
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "3400"]
