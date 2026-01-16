FROM python:3.12-alpine

ARG RELEASE_VERSION
ENV RELEASE_VERSION=${RELEASE_VERSION}
ENV PYTHONPATH="/sonobarr/src"

RUN apk update && apk add --no-cache su-exec \
	&& addgroup -S -g 1000 sonobarr \
	&& adduser -S -G sonobarr -u 1000 sonobarr

# Copy only requirements first
COPY requirements.txt /sonobarr/
WORKDIR /sonobarr

# Install requirements
RUN pip install --no-cache-dir -r requirements.txt


# Now copy the rest of your code
COPY src/ /sonobarr/src/
COPY migrations/ /sonobarr/migrations/
COPY gunicorn_config.py /sonobarr/
COPY init.sh /sonobarr/

RUN chmod 755 init.sh \
	&& mkdir -p /sonobarr/config \
	&& chown -R sonobarr:sonobarr /sonobarr/config

ENTRYPOINT ["./init.sh"]
