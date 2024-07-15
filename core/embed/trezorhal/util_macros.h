#ifndef _UTIL_MACROS_H_
#define _UTIL_MACROS_H_

#define UNUSED_VAR(X) ((void)(X))

#define JOIN_EXPR(a, b, c) a##_##b##_##c
// regex ->(JOIN_EXPR\((.*), (.*), (.*)\).*,).*
// replace -> $1 // $2_$3_$4

#define ENUM_NAME_ARRAY_ITEM(x) [x] = #x

#define ExecuteCheck_ADV(expr, expected_result, on_false) \
  {                                                       \
    typeof(expected_result) ret = (expr);                 \
    if (ret != (expected_result)) {                       \
      on_false                                            \
    }                                                     \
  }

#include <stdbool.h>
#include <stdint.h>
#define EXEC_RETRY(MAX_RETRY, ON_INIT, ON_LOOP, ON_SUCCESS, ON_FALSE) \
  {                                                                   \
    bool loop_exec() { (ON_LOOP); }                                   \
    bool loop_result = false;                                         \
    (ON_INIT);                                                        \
    for (uint32_t retry = 0; retry < MAX_RETRY; retry++) {            \
      loop_result = loop_exec();                                      \
      if (loop_result) break;                                         \
    }                                                                 \
    if (loop_result)                                                  \
      (ON_SUCCESS);                                                   \
    else                                                              \
      (ON_FALSE);                                                     \
  }

#endif  // _UTIL_MACROS_H_