"""`_is_test` must not misclassify real functions named like tests.

Each language's test detector anchors to path SEGMENTS plus the language's real test-file
convention. A production function named `test_connection` / `testConnection` / `TestRunner`
in a NON-test file must stay an analyzable function (not be dropped from the entry-point
set), while genuine test files are still recognized.
"""

from __future__ import annotations

from logicchart.analysis.languages.c import _is_test as c_is_test
from logicchart.analysis.languages.cpp import _is_test as cpp_is_test
from logicchart.analysis.languages.csharp import _is_test as csharp_is_test
from logicchart.analysis.languages.java import _is_test as java_is_test
from logicchart.analysis.languages.php import _is_test as php_is_test
from logicchart.analysis.languages.ruby import _is_test as ruby_is_test
from logicchart.analysis.languages.rust import _is_test as rust_is_test
from logicchart.analysis.python import _is_test as python_is_test
from logicchart.analysis.typescript import _is_test as ts_is_test


def test_typescript_real_function_named_like_test_is_not_a_test() -> None:
    # `testConnection`, `testimonial`, `shouldRetry` in a production file are real.
    assert not ts_is_test("src/api/client.ts", "testConnection")
    assert not ts_is_test("src/ui/Testimonial.tsx", "testimonial")
    assert not ts_is_test("src/lib/retry.ts", "shouldRetry")
    assert not ts_is_test("src/lib/iterate.ts", "iterate")
    # Genuine test files are still detected, whatever the function name.
    assert ts_is_test("src/__tests__/client.ts", "connect")
    assert ts_is_test("src/api/client.test.ts", "helper")
    assert ts_is_test("src/api/client.spec.ts", "helper")


def test_c_real_function_named_like_test_is_not_a_test() -> None:
    assert not c_is_test("src/network.c", "test_connection")
    assert not c_is_test("src/contest.c", "score")  # `test` is a substring, not a segment
    assert not c_is_test("src/latest/run.c", "run")  # `latest` contains `test`
    assert c_is_test("tests/network.c", "anything")
    assert c_is_test("src/test_network.c", "anything")
    assert c_is_test("src/network_test.c", "anything")


def test_cpp_real_function_named_like_test_is_not_a_test() -> None:
    assert not cpp_is_test("src/network.cpp", "test_connection")
    assert not cpp_is_test("src/contest.cpp", "score")
    assert not cpp_is_test("src/latest/router.hpp", "route")
    assert cpp_is_test("tests/network.cpp", "anything")
    assert cpp_is_test("src/test_network.cpp", "anything")
    assert cpp_is_test("src/network_test.hpp", "anything")


def test_rust_real_function_named_like_test_is_not_a_test() -> None:
    # A bare `test`-prefixed name in src/ is a real function, not a Rust test.
    assert not rust_is_test("src/render.rs", "test_render")
    assert not rust_is_test("src/contest.rs", "score")
    # The integration `tests/` directory is the path convention this signature can detect.
    assert rust_is_test("tests/integration.rs", "anything")
    assert rust_is_test("crate/tests/api.rs", "anything")


def test_csharp_real_method_named_like_test_is_not_a_test() -> None:
    assert not csharp_is_test("src/TestRunner.cs", "TestData")
    assert not csharp_is_test("src/Latest.cs", "Get")
    assert csharp_is_test("test/SvcTests.cs", "Run")
    assert csharp_is_test("src/SvcTest.cs", "Run")
    assert csharp_is_test("src/SvcTests.cs", "Run")


def test_java_real_method_named_like_test_is_not_a_test() -> None:
    # `testConnection` in a production class is a real method, not a JUnit test.
    assert not java_is_test("src/main/java/com/svc/Svc.java", "testConnection")
    assert not java_is_test("src/main/java/com/svc/Latest.java", "get")
    assert java_is_test("src/test/java/com/svc/SvcTest.java", "run")
    assert java_is_test("src/main/java/com/svc/SvcTests.java", "run")
    assert java_is_test("src/main/java/com/svc/SvcIT.java", "run")


def test_php_real_function_named_like_test_is_not_a_test() -> None:
    # The old `*test.php` substring matched legitimate files; drop it.
    assert not php_is_test("src/request.php", "test")
    assert not php_is_test("src/latest.php", "run")
    assert not php_is_test("src/Service.php", "testConnection")
    assert php_is_test("tests/ServiceTest.php", "run")
    assert php_is_test("src/ServiceTest.php", "run")


def test_ruby_real_method_named_like_test_is_not_a_test() -> None:
    assert not ruby_is_test("lib/helper.rb", "test_helper")
    assert not ruby_is_test("lib/contest.rb", "score")
    assert ruby_is_test("spec/service_spec.rb", "run")
    assert ruby_is_test("test/service_test.rb", "run")
    assert ruby_is_test("lib/service_spec.rb", "run")


def test_python_reference_behaviour_is_preserved() -> None:
    # Python (a correct reference) keeps `test_` prefix + `tests` segment semantics.
    assert python_is_test("tests/test_users.py", "test_login")
    assert python_is_test("pkg/test_users.py", "anything")
    assert not python_is_test("pkg/users.py", "testimonial")
