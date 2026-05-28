```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from enum import Enum
import re


class OperationType(Enum):
    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    DIVIDE = "/"
    POWER = "^"
    MODULO = "%"


class Operation(ABC):
    @abstractmethod
    def execute(self, a: float, b: float) -> float:
        ...

    @abstractmethod
    def get_symbol(self) -> str:
        ...


class Add(Operation):
    def execute(self, a: float, b: float) -> float:
        return a + b

    def get_symbol(self) -> str:
        return OperationType.ADD.value


class Subtract(Operation):
    def execute(self, a: float, b: float) -> float:
        return a - b

    def get_symbol(self) -> str:
        return OperationType.SUBTRACT.value


class Multiply(Operation):
    def execute(self, a: float, b: float) -> float:
        return a * b

    def get_symbol(self) -> str:
        return OperationType.MULTIPLY.value


class Divide(Operation):
    def execute(self, a: float, b: float) -> float:
        if b == 0:
            raise ZeroDivisionError("Division by zero is not allowed.")
        return a / b

    def get_symbol(self) -> str:
        return OperationType.DIVIDE.value


class Power(Operation):
    def execute(self, a: float, b: float) -> float:
        return a ** b

    def get_symbol(self) -> str:
        return OperationType.POWER.value


class Modulo(Operation):
    def execute(self, a: float, b: float) -> float:
        if b == 0:
            raise ZeroDivisionError("Modulo by zero is not allowed.")
        return a % b

    def get_symbol(self) -> str:
        return OperationType.MODULO.value


class OperationFactory:
    _operations: dict[OperationType, type[Operation]] = {
        OperationType.ADD: Add,
        OperationType.SUBTRACT: Subtract,
        OperationType.MULTIPLY: Multiply,
        OperationType.DIVIDE: Divide,
        OperationType.POWER: Power,
        OperationType.MODULO: Modulo,
    }

    @classmethod
    def create(cls, op_type: OperationType) -> Operation:
        if op_type not in cls._operations:
            raise ValueError(f"Unknown operation: {op_type}")
        return cls._operations[op_type]()


class CalculationResult:
    def __init__(self, operand_a: float, operand_b: float, operation: Operation, result: float):
        self.operand_a = operand_a
        self.operand_b = operand_b
        self.operation = operation
        self.result = result

    def __str__(self) -> str:
        return f"{self.operand_a} {self.operation.get_symbol()} {self.operand_b} = {self.result}"

    def __repr__(self) -> str:
        return (
            f"CalculationResult({self.operand_a}, {self.operand_b}, "
            f"{self.operation.get_symbol()}, {self.result})"
        )


class History:
    def __init__(self):
        self._entries: List[CalculationResult] = []

    def add_entry(self, entry: CalculationResult) -> None:
        self._entries.append(entry)

    def get_all(self) -> List[CalculationResult]:
        return list(self._entries)

    def get_last(self) -> Optional[CalculationResult]:
        return self._entries[-1] if self._entries else None

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def __str__(self) -> str:
        return "\n".join(str(entry) for entry in self._entries)


class Parser:
    _pattern = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([+\-*/^%])\s*(-?\d+(?:\.\d+)?)\s*$")

    @staticmethod
    def parse(expression: str) -> tuple[float, OperationType, float]:
        match = Parser._pattern.match(expression)
        if not match:
            raise ValueError(
                "Invalid expression format. Use: <number> <operator> <number> "
                "(e.g., '5 + 3, '10.5 * 2')"
            )
        a = float(match.group(1))
        op_symbol = match.group(2)
        b = float(match.group(3))

        op_map = {op.value: op for op in OperationType}
        if op_symbol not in op_map:
            raise ValueError(f"Unknown operator: {op_symbol}")

        return a, op_map[op_symbol], b


class Calculator:
    def __init__(self):
        self._history = History()

    @property
    def history(self) -> History:
        return self._history

    def calculate(self, expression: str) -> CalculationResult:
        a, op_type, b = Parser.parse(expression)
        operation = OperationFactory.create(op_type)
        result = operation.execute(a, b)
        calc_result = CalculationResult(a, b, operation, result)
        self._history.add_entry(calc_result)
        return calc_result

    def add(self, a: float, b: float) -> CalculationResult:
        return self.calculate(f"{a} + {b}")

    def subtract(self, a: float, b: float) -> CalculationResult:
        return self.calculate(f"{a} - {b}")

    def multiply(self, a: float, b: float) -> CalculationResult:
        return self.calculate(f"{a} * {b}")

    def divide(self, a: float, b: float) -> CalculationResult:
        return self.calculate(f"{a} / {b}")

    def power(self, a: float, b: float) -> CalculationResult:
        return self.calculate(f"{a} ^ {b}")

    def modulo(self, a: float, b: float) -> CalculationResult:
        return self.calculate(f"{a} % {b}")


class CalculatorUI:
    def __init__(self):
        self._calculator = Calculator()

    def run(self) -> None:
        print("=" * 50)
        print("  OWL Calculator")
        print("=" * 50)
        print("Supported operations: +  -  *  /  ^  %")
        print("Enter expressions like: 5 + 3")
        print("Commands: 'history', 'clear', 'quit'")
        print("-" * 50)

        while True:
            try:
                user_input = input("\n>>> ").strip()

                if not user_input:
                    continue

                if user_input.lower() == "quit":
                    print("Goodbye!")
                    break

                if user_input.lower() == "history":
                    history = self._calculator.history
                    if len(history) == 0:
                        print("No calculations yet.")
                    else:
                        print("\n--- History ---")
                        print(history)
                        print("---------------")
                    continue

                if user_input.lower() == "clear":
                    self._calculator.history.clear()
                    print("History cleared.")
                    continue

                result = self._calculator.calculate(user_input)
                print(f"= {result.result}")

            except ZeroDivisionError as e:
                print(f"Error: {e}")
            except ValueError as e:
                print(f"Error: {e}")
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break


def main() -> None:
    ui = CalculatorUI()
    ui.run()


if __name__ == "__main__":
    main()
```