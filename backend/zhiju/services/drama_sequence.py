from sqlalchemy import case, func, select

from zhiju.models import Drama


def drama_sequence_subquery():
    return (
        select(
            Drama.id.label("drama_id"),
            func.row_number()
            .over(
                order_by=(
                    case((Drama.source_row_number.is_(None), 1), else_=0),
                    Drama.source_row_number.asc(),
                    Drama.drama_number.asc(),
                )
            )
            .label("sequence_number"),
        )
        .subquery()
    )
