FROM python:latest

WORKDIR /app

# Add some silly layers
RUN touch file1.txt
RUN echo "hello" > file2.txt
RUN mkdir -p /app/test

COPY . /app

CMD ["python", "main.py"]
