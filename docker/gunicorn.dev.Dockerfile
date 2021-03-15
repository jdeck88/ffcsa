# pull official base image
FROM python:3.9.1
# FROM python:3.9-slim-buster
# FROM python:3.9-buster
# FROM ubuntu:hirsute

RUN \
    apt-get -qq update && \
    # apt-get -q -y upgrade && \
    apt install -y libpq-dev && \
    apt-get install -y sudo curl wget locales && \
    # apt-get install -y sudo memcached libmemcached-tools && \
    sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    # apt-get -y install libssl-dev default-libmysqlclient-dev && \
    rm -rf /var/lib/apt/lists/*


# set work directory
WORKDIR /app


RUN locale-gen en_US.UTF-8
# ENV LANG en_US.UTF-8
# ENV LANGUAGE en_US:en
# ENV LC_ALL en_US.UTF-8
 

RUN pip install --upgrade pip
# COPY ../requirements.current.txt .

# copy project
COPY ../ .
RUN pip install -r requirements.current.txt