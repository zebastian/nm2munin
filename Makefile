# nm2munin -- convenience wrapper around the manager/bridge deploy scripts.
# ENV selects the manager config (default: config/manager.env).
ENV ?= config/manager.env

.PHONY: render install uninstall lint clean

render:                 ## render manager config -> build/ (touches nothing)
	deploy/render.sh $(ENV)

install:                ## render + install the manager/bridge (run as root)
	deploy/install.sh $(ENV)

uninstall:              ## stop/disable units and remove manager files
	deploy/uninstall.sh $(ENV)

lint:                   ## syntax-check python + shell
	python3 -m py_compile src/nm2munin/*.py tools/*.py \
		examples/two-node-lab/dummy-traffic/*.py
	bash -n deploy/*.sh examples/two-node-lab/*.sh
	@command -v shellcheck >/dev/null && \
		shellcheck deploy/render.sh deploy/install.sh deploy/uninstall.sh \
		           examples/two-node-lab/*.sh || true

clean:
	rm -rf build examples/*/build
