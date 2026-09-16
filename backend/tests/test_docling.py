from docling.document_converter import DocumentConverter

source = r"D:\pythonWorkSpace\projects\adaptiveKnowledgeRAG\docs\A_10_Gb_s_Hybrid_ADC-Based_Receiver_With_Embedded_Analog_and_Per-Symbol_Dynamically_Enabled_Digital_Equalization.pdf"  # 你的专业 PDF 路径
converter = DocumentConverter()
result = converter.convert(source)

# 导出为 Markdown 格式（公式和表格会自动转换）
markdown_content = result.document.export_to_markdown()
print(markdown_content)