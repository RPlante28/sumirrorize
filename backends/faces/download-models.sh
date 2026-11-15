#!/bin/sh
# gets the face models into ./models, for running outside Docker
set -e
cd "$(dirname "$0")"
mkdir -p models
base=https://github.com/opencv/opencv_zoo/raw/main/models
curl -fsSL -o models/face_detection_yunet_2023mar.onnx "$base/face_detection_yunet/face_detection_yunet_2023mar.onnx"
curl -fsSL -o models/face_recognition_sface_2021dec.onnx "$base/face_recognition_sface/face_recognition_sface_2021dec.onnx"
curl -fsSL -o models/open_closed_eye.onnx https://storage.openvinotoolkit.org/repositories/open_model_zoo/public/2022.1/open-closed-eye-0001/open_closed_eye.onnx
sha256sum -c <<SUMS
8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4  models/face_detection_yunet_2023mar.onnx
0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79  models/face_recognition_sface_2021dec.onnx
4daa100034482525a26c9afb9297c16580a531189e66e3d2b2ac7d32becfd593  models/open_closed_eye.onnx
SUMS
