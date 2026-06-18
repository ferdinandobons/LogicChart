#include <string>

enum class CacheTier {
  Cold,
  Warm,
  Hot,
};

class NativePolicy {
public:
  int ttl(CacheTier tier, bool degraded, bool paid_customer) {
    if (degraded) {
      return paid_customer ? 45 : 30;
    }
    switch (tier) {
      case CacheTier::Cold:
        return paid_customer ? 120 : 60;
      case CacheTier::Warm:
        return paid_customer ? 600 : 300;
      case CacheTier::Hot:
        return paid_customer ? 1200 : 900;
      default:
        return 120;
    }
  }
};
