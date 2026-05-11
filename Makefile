.PHONY: deploy deploy-bootstrap check lint deps clean

VAULT_TPL := group_vars/timeservers/vault.yml.tpl
VAULT_YML := group_vars/timeservers/vault.yml

# Normal idempotent re-run (admin SSH key must already be deployed)
deploy: $(VAULT_YML)
	ansible-playbook playbook.yml
	@rm -f $(VAULT_YML)

# First-run: Pi Imager creates admin user with password auth
deploy-bootstrap: $(VAULT_YML)
	ansible-playbook playbook.yml -u admin --ask-pass
	@rm -f $(VAULT_YML)

# Dry-run with diff (does not make changes)
check: $(VAULT_YML)
	ansible-playbook playbook.yml --check --diff
	@rm -f $(VAULT_YML)

$(VAULT_YML): $(VAULT_TPL)
	op inject -i $< -o $@

deps:
	ansible-galaxy collection install -r requirements.yml

lint:
	ansible-lint playbook.yml

clean:
	rm -f $(VAULT_YML)
	rm -rf .ansible_cache
