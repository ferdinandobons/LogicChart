#include <string>

namespace backend {

struct Request {
  int shard;
  bool authenticated;
  bool warm_cache;
  bool write_operation;
};

class AdmissionControl {
public:
  bool allow(const Request& request) {
    if (!request.authenticated) {
      return false;
    }
    if (request.shard < 0) {
      return false;
    }
    if (request.write_operation && retry_budget(request, 0) == 0) {
      return false;
    }
    return route(request.shard) != "reject";
  }

  std::string route(int shard) {
    switch (shard % 4) {
      case 0:
        return "primary";
      case 1:
        return "secondary";
      case 2:
        return "analytics";
      default:
        return "overflow";
    }
  }

  int retry_budget(const Request& request, int attempts) {
    if (request.warm_cache && attempts < 2) {
      return 2 - attempts;
    }
    if (!request.warm_cache && attempts == 0) {
      return 1;
    }
    if (request.write_operation && attempts < 1) {
      return 1;
    }
    return 0;
  }
};

}  // namespace backend
