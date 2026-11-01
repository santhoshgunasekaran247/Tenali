from decimal import Decimal
from typing import Annotated

from pydantic import Field

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
SignedMoney = Annotated[Decimal, Field(max_digits=14, decimal_places=2, allow_inf_nan=False)]
