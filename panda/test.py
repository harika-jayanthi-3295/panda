while True:
    reply model(system,messages,tools)
    if not reply.tool_calls:
        return reply.text
    for call in reply.tool_calls:
        get(call)
        result = tools[call.name].run(**call.args)
        message.append(result)