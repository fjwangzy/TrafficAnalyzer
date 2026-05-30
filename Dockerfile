FROM python:3.10.13

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m pip install --upgrade pip
RUN pip3 install "numpy<2" "setuptools<70.0" wheel cython
RUN pip3 install --no-build-isolation cython_bbox==0.1.5 lap==0.4.0 
RUN pip3 install torch==2.3.1 torchvision==0.18.1 
# --index-url https://download.pytorch.org/whl/cu121

#首先，仅复制 requirements.txt 并安装依赖
COPY requirements.txt /app/
RUN pip3 install -r requirements.txt

#然后，复制剩余的代码
COPY . /app
