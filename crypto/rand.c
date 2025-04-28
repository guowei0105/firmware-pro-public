/**
 * Copyright (c) 2013-2014 Tomas Dzetkulic
 * Copyright (c) 2013-2014 Pavol Rusnak
 *
 * Permission is hereby granted, free of charge, to any person obtaining
 * a copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included
 * in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
 * OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
 * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES
 * OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
 * ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 * OTHER DEALINGS IN THE SOFTWARE.
 */

#include "rand.h"

#ifndef RAND_PLATFORM_INDEPENDENT

#pragma message( \
    "NOT SUITABLE FOR PRODUCTION USE! Replace random32() function with your own secure code.")

// The following code is not supposed to be used in a production environment.
// It's included only to make the library testable.
// The message above tries to prevent any accidental use outside of the test
// environment.
//
// You are supposed to replace the random8() and random32() function with your
// own secure code. There is also a possibility to replace the random_buffer()
// function as it is defined as a weak symbol.

static uint32_t seed = 0;  // 随机数种子初始化为0

void random_reseed(const uint32_t value) { seed = value; }  // 重新设置随机数种子的函数

uint32_t random32(void) {
  // Linear congruential generator from Numerical Recipes
  // https://en.wikipedia.org/wiki/Linear_congruential_generator
  // 线性同余生成器，来自《数值计算方法》
  seed = 1664525 * seed + 1013904223;  // 使用线性同余公式计算新的种子值
  return seed;  // 返回生成的随机数
}

#endif /* RAND_PLATFORM_INDEPENDENT */

//
// The following code is platform independent
// 以下代码与平台无关
//

void __attribute__((weak)) random_buffer(uint8_t *buf, size_t len) {  // 生成随机字节缓冲区的函数，weak属性允许被覆盖
  uint32_t r = 0;  // 临时存储32位随机数
  for (size_t i = 0; i < len; i++) {  // 遍历缓冲区的每个字节
    if (i % 4 == 0) {  // 每4个字节生成一个新的随机数
      r = random32();  // 获取一个新的32位随机数
    }
    buf[i] = (r >> ((i % 4) * 8)) & 0xFF;  // 从32位随机数中提取8位作为当前字节
  }
}

uint32_t random_uniform(uint32_t n) {  // 生成[0,n-1]范围内均匀分布的随机数
  uint32_t x = 0, max = 0xFFFFFFFF - (0xFFFFFFFF % n);  // 计算不会导致偏差的最大值
  while ((x = random32()) >= max)  // 循环直到生成小于max的随机数
    ;
  return x / (max / n);  // 将随机数映射到[0,n-1]范围
}

void random_permute(char *str, size_t len) {  // 随机打乱字符串中字符的顺序
  for (int i = len - 1; i >= 1; i--) {  // 从后向前遍历字符串
    int j = random_uniform(i + 1);  // 随机选择一个位置j，范围是[0,i]
    char t = str[j];  // 交换位置i和位置j的字符
    str[j] = str[i];  // 交换操作
    str[i] = t;  // 完成交换
  }
}
