TARGETS := all clean venv build upload monitor benchmark test-security test-native smoke-test

.PHONY: $(TARGETS)

$(TARGETS):
	$(MAKE) -C ESP32_Auth_PIO $@
