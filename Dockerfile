# syntax=docker/dockerfile:1
#######################################################################################
# Copyright ETSI Contributors and Others.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#######################################################################################


######################
# Stage 1: Base Stage#
######################

FROM python:3.10-alpine AS base

# RUN apk add --no-cache \
#   libgcc \
#   libstdc++

ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PIP_DISABLE_PIP_VERSION_CHECK=1


#########################################################################################################################################################################

########################
# Stage 2: Build Stage #
########################

FROM base AS build

# Install required system packages
RUN apk add --no-cache \
  build-base \
  git \
  patch \
  curl \
  zlib-dev \
  cdrkit \
  linux-headers \
  openssl \
  openssl-dev \
  libffi-dev \
  libmagic \
  cargo \
  rust \
  musl-dev \
  bash \
  openssh-client

# Verify git installation
RUN git --version

WORKDIR /app/ro

# Isolate dependencies in a venv
RUN python -m venv /app/ro/.venv
ENV PATH="/app/ro/.venv/bin:$PATH"

ARG COMMON_REFSPEC=master
ARG IM_REFSPEC=master

# Install build tools
RUN pip install -U pip setuptools wheel build

RUN test -x /app/ro/.venv/bin/python && /app/ro/.venv/bin/python -c "import sys; print(sys.prefix)"

# Install OSM dependency modules

RUN git clone --filter=blob:none --tags https://osm.etsi.org/gitlab/osm/common.git /tmp/osm-common && \
  cd /tmp/osm-common && \
  git fetch origin ${COMMON_REFSPEC} && \
  git checkout FETCH_HEAD && \
  cd - && \
  pip install -r /tmp/osm-common/requirements.txt && \
  pip install /tmp/osm-common

COPY requirements.txt ./

# Install py-radix from source with a one-line patch (no build isolation)
RUN \
    # py-radix is installed as dependency of the ipconflict package
    # the installation is a bit special as it is not fully compatible with Alpine library versions
    # similar issue reported here: https://github.com/mjschultz/py-radix/issues/70
    git clone --filter=blob:none https://github.com/mjschultz/py-radix.git /tmp/py-radix && \
    sed -i 's/from setuptools\.dist import Version/from packaging.version import Version/' /tmp/py-radix/setup.py && \
    pip install --no-build-isolation /tmp/py-radix && \
    pip install -r requirements.txt

RUN pip install git+https://github.com/mjschultz/py-radix.git && \
    pip install -r requirements.txt

COPY . .

RUN for component in common RO-plugin NG-RO RO-VIM-* RO-SDN-*; do \
    if [ -d "$component" ]; then \
        python -m build $component && \
        pip install $component/dist/*.whl; \
    fi; \
    done


################################################################################################################################################################

########################
# Stage 3: Final Stage #
########################

FROM base AS final
WORKDIR /app

RUN apk add --no-cache \
      cdrkit \
      git \
      curl \
      libmagic \
      bash

RUN addgroup -g 1000 appuser && \
    adduser -D -G appuser -u 1000 appuser -h /app appuser && \
    mkdir -p /app/storage/kafka && \
    mkdir -p /app/log && \
    chown -R appuser:appuser /app

USER appuser:appuser

ENV VIRTUAL_ENV=/app/.venv \
  PATH="/app/.venv/bin:$PATH"

COPY --from=build --chown=appuser:appuser /app/ro/ /app/

EXPOSE 9090

# Database configuration
ENV RO_DB_HOST="" \
    RO_DB_OVIM_HOST="" \
    RO_DB_ROOT_PASSWORD="" \
    RO_DB_OVIM_ROOT_PASSWORD="" \
    RO_DB_USER=mano \
    RO_DB_OVIM_USER=mano \
    RO_DB_PASSWORD=manopw \
    RO_DB_OVIM_PASSWORD=manopw \
    RO_DB_PORT=3306 \
    RO_DB_OVIM_PORT=3306 \
    RO_DB_NAME=mano_db \
    RO_DB_OVIM_NAME=mano_vim_db \
    OPENMANO_TENANT=osm

# Application configuration
ENV OSMRO_DATABASE_DRIVER=mongo \
    OSMRO_DATABASE_URI=mongodb://mongo:27017 \
    OSMRO_MESSAGE_DRIVER=kafka \
    OSMRO_MESSAGE_HOST=kafka \
    OSMRO_MESSAGE_PORT=9092 \
    OSMRO_LOG_LEVEL=INFO

# Expose ports and volumes
VOLUME /var/log/osm

# Set user and entrypoint
USER appuser
CMD ["python", "-u", "-m", "osm_ng_ro.ro_main"]

