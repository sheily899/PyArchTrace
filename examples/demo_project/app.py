"""极小应用请求处理示例，仅供扫描演示；不会被工具执行。"""


class RequestGateway:
    def receive(self, request: str) -> str:
        return request


class RequestClassifier:
    def classify(self, request: str) -> str:
        if request.startswith("priority:"):
            return "priority"
        return "standard"


def handle_request(request: str) -> str:
    gateway = RequestGateway()
    category = RequestClassifier().classify(gateway.receive(request))
    return f"Routed to {category} processing"
