CURRENT_DIR = $(shell pwd)
PROJECT_NAME = artinder
PORT_JUPYTER = 8888

build-network:
	docker network create service_network -d bridge || true

build:
	docker build -t ${PROJECT_NAME}:dev .

build-jupyter:
	docker build -f Dockerfile.jupyter -t ${PROJECT_NAME}:jupyter .

run: build-network
	docker run -it --rm \
	    --env-file ${CURRENT_DIR}/.env \
	    -p ${PORT}:8888 \
	    -v "${CURRENT_DIR}/src:/srv/src" \
	    -v "${CURRENT_DIR}/data:/srv/data" \
		--network service_network \
	    --name ${PROJECT_NAME}_container \
	    ${PROJECT_NAME}:dev scrape

jupyter: build-network
	docker run -d --rm \
	    --env-file ${CURRENT_DIR}/.env \
	    -p ${PORT_JUPYTER}:8888 \
	    -v "${CURRENT_DIR}/src:/srv/src" \
	    -v "${CURRENT_DIR}/data:/srv/data" \
		--network service_network \
	    --name ${PROJECT_NAME}_jupyter_container \
	    ${PROJECT_NAME}:jupyter

run-debug:
	docker run -it --rm \
	    --env-file ${CURRENT_DIR}/.env \
	    -v "${CURRENT_DIR}/src:/srv/src" \
	    -v "${CURRENT_DIR}/data:/srv/data" \
	    --name ${PROJECT_NAME}_container \
	    ${PROJECT_NAME}:dev bash

mongo: build-network
	docker run -d \
		-v "${CURRENT_DIR}/data/mongo_data:/data/db"\
		-p 27018:27017 \
	    --name ${PROJECT_NAME}_mongo \
		--network service_network \
		mongo:6.0.5

stop:
	docker rm -f techcrunch_scraper

stop-jupyter:
	docker rm -f ${PROJECT_NAME}_jupyter_container

stop-mongo:
	docker rm -f ${PROJECT_NAME}_mongo
