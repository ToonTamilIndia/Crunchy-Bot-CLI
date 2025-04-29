FROM python:3.12-slim

RUN apt -qq update && apt -qq install -y git wget ffmpeg
 
COPY . . 

RUN pip3 install -r requirements.txt 

CMD ["python3","tg.py"]
