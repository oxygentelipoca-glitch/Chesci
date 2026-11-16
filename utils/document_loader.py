import os


def _read_text_with_fallback(file_path: str) -> str:
    encodings = (
        "utf-8",
        "utf-8-sig",
        "gb18030",
        "gbk",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
        "big5",
    )

    last_error = None
    with open(file_path, "rb") as f:
        raw = f.read()

    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc

    raise UnicodeDecodeError(
        "text",
        raw,
        0,
        len(raw),
        f"无法使用常见编码读取文件: {os.path.basename(file_path)}"
    ) from last_error


def load_documents(
    folder_path="documents"
):

    documents = []


    for filename in os.listdir(folder_path):

        # Finder and editor metadata must never become knowledge chunks.
        if filename.startswith("."):
            continue

        file_path = os.path.join(
            folder_path,
            filename
        )


        if os.path.isfile(file_path):

            user_id = "system"
            original_filename = filename
            if "__" in filename:
                user_id_str, original_filename = filename.split("__", 1)
                if user_id_str.isdigit():
                    user_id = user_id_str

            content = _read_text_with_fallback(file_path)


            documents.append(
                {
                    "text": content,
                    "filename": original_filename,
                    "stored_filename": filename,
                    "user_id": user_id
                }
            )


    return documents
