#include "crypto_util.h"

#include <Arduino.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void hexStringToBytes(const char* hexString, uint8_t* byteArr, size_t maxLen) {
    size_t len = strlen(hexString);
    if (len > maxLen * 2) len = maxLen * 2;
    for (size_t i = 0; i < len; i += 2) {
        char byteChars[3] = {hexString[i], hexString[i + 1], '\0'};
        byteArr[i / 2] = (uint8_t) strtol(byteChars, NULL, 16);
    }
}

void bytesToHexString(const uint8_t* byteArr, size_t len, char* hexString) {
    for (size_t i = 0; i < len; i++) {
        sprintf(&hexString[i * 2], "%02X", byteArr[i]);
    }
    hexString[len * 2] = '\0';
}

void getRandomBytes(uint8_t* buf, size_t len) {
    for (size_t i = 0; i < len; i++) {
        buf[i] = esp_random() & 0xFF;
    }
}
