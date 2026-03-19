CURRENT_DIR = $(shell pwd)
PROJECT_NAME = art_scraper
include .env
export

prepare-dirs:
	mkdir -p data || true && \
	mkdir -p data/artists_raw_html || true && \
	mkdir -p data/artworks_raw_html || true && \
	mkdir -p data/art_links || true && \
	mkdir -p data/nltk_dir || true

build-network:
	docker network create service_network -d bridge || true

build:
	docker build -t ${PROJECT_NAME}:dev .

build-jupyter:
	docker build -f Dockerfile.jupyter -t ${PROJECT_NAME}:jupyter .

code-version:
	git log --oneline --format=%h -n1 > ${CURRENT_DIR}/src/code_vesrion.txt

run-dev:
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml PYTHONPATH=${CURRENT_DIR}/src \
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	python3 ${CURRENT_DIR}/src/main.py --pipeline wikidata

run: build-network code-version prepare-dirs
	docker run -it --rm \
	    --env-file ${CURRENT_DIR}/.env \
	    -v "${CURRENT_DIR}/src:/srv/src" \
	    -v "${CURRENT_DIR}/data:/srv/data" \
		--network service_network \
	    ${PROJECT_NAME}:dev ${PIPELINE}

build-search-index: build-network code-version prepare-dirs
	docker run -it --rm \
	    --env-file ${CURRENT_DIR}/.env \
	    -v "${CURRENT_DIR}/src:/srv/src" \
	    -v "${CURRENT_DIR}/data:/srv/data" \
		--network service_network \
	    ${PROJECT_NAME}:dev "python3" src/prepare_search_index.py

run-jupyter: build-network
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

analysis:
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml PYTHONPATH=${CURRENT_DIR}/src \
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	python3 ${CURRENT_DIR}/src/main.py --pipeline analysis
