ARG BUILD_FROM
FROM ${BUILD_FROM}

# Synchronize with homeassistant/core.py:async_stop
ENV \
    S6_SERVICES_GRACETIME=220000

WORKDIR /usr/src

## Setup Home Assistant Core dependencies
COPY requirements.txt homeassistant/
COPY homeassistant/package_constraints.txt homeassistant/homeassistant/
RUN \ 
   cat homeassistant/requirements.txt | grep -v ^# | grep -v ^- | xargs -P 6 -n 4 -- \
   pip3 download --no-index --only-binary=:all: \
   --find-links "${WHEELS_LINKS}" --use-deprecated=legacy-resolver \
   --cache-dir "/tmp/pip_cache"
RUN \
    pip3 install --cache-dir "/tmp/pip_cache" --no-index --only-binary=:all: --find-links "${WHEELS_LINKS}" \
    -r homeassistant/requirements.txt --use-deprecated=legacy-resolver ; exit 0
COPY requirements_all.txt homeassistant/
RUN \ 
   cat homeassistant/requirements_all.txt | grep -v ^# | grep -v ^- | xargs -P 8 -n 120 -- \
   pip3 download --no-index --only-binary=:all: \
   --find-links "${WHEELS_LINKS}" --use-deprecated=legacy-resolver \
   --cache-dir "/tmp/pip_cache" ; exit 0
RUN \
    pip3 install --cache-dir "/tmp/pip_cache" --no-index --only-binary=:all: --find-links "${WHEELS_LINKS}" \
    -r homeassistant/requirements_all.txt --use-deprecated=legacy-resolver

## Setup Home Assistant Core
COPY . homeassistant/
RUN \
    pip3 install --no-cache-dir --no-index --only-binary=:all: --find-links "${WHEELS_LINKS}" \
    -e ./homeassistant --use-deprecated=legacy-resolver \
    && python3 -m compileall homeassistant/homeassistant

# Fix Bug with Alpine 3.14 and sqlite 3.35
# https://gitlab.alpinelinux.org/alpine/aports/-/issues/12524
ARG BUILD_ARCH
RUN \
    if [ "${BUILD_ARCH}" = "amd64" ]; then \
        export APK_ARCH=x86_64; \
    elif [ "${BUILD_ARCH}" = "i386" ]; then \
        export APK_ARCH=x86; \
    else \
        export APK_ARCH=${BUILD_ARCH}; \
    fi \
    && curl -O http://dl-cdn.alpinelinux.org/alpine/v3.13/main/${APK_ARCH}/sqlite-libs-3.34.1-r0.apk \
    && apk add --no-cache sqlite-libs-3.34.1-r0.apk \
    && rm -f sqlite-libs-3.34.1-r0.apk

# Home Assistant S6-Overlay
COPY rootfs /

WORKDIR /config
