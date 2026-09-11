// Shared helpers used by all three authentication protocols:
// hex conversion and random byte generation.
#pragma once

#include <stddef.h>
#include <stdint.h>

// Decodes an ASCII hex string into bytes, writing at most maxLen bytes.
void hexStringToBytes(const char* hexString, uint8_t* byteArr, size_t maxLen);

// Encodes len bytes as uppercase ASCII hex. hexString must hold len*2 + 1 bytes.
void bytesToHexString(const uint8_t* byteArr, size_t len, char* hexString);

// Fills buf with len bytes from the hardware RNG.
void getRandomBytes(uint8_t* buf, size_t len);
