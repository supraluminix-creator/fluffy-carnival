# OpenAPI Documentation

This directory contains OpenAPI specification files for the fluffy-carnival API.

## Files

- `schema-draft.yaml` - Initial OpenAPI 3.0 specification draft
- `README.md` - This documentation file

## Usage

The OpenAPI specification defines the REST API endpoints, request/response schemas, and authentication methods for the fluffy-carnival service.

### Viewing the Specification

You can view the API specification using:

1. **Swagger UI**: Copy the `schema-draft.yaml` content to [Swagger Editor](https://editor.swagger.io/)
2. **Local tools**: Use tools like `swagger-ui-serve` or `redoc-cli` to generate documentation locally
3. **IDE Integration**: Most modern IDEs support OpenAPI spec viewing and validation

### Future Development

This is an initial draft. Future enhancements will include:

1. Complete endpoint definitions for all collector APIs
2. Authentication and authorization specifications  
3. Real-time WebSocket API documentation
4. Prometheus metrics endpoint documentation
5. Error response schemas and examples

## API Structure

The API is organized into the following main sections:

- **Health**: Basic health check endpoints
- **Collectors**: Data collection and management endpoints
- **Orchestrator**: Parallel execution and scheduling endpoints
- **Metrics**: Prometheus metrics and monitoring endpoints
- **WebSocket**: Real-time data streaming endpoints (future)

## Contributing

When adding new API endpoints:

1. Update the OpenAPI specification in `schema-draft.yaml`
2. Add examples for request/response payloads
3. Document error conditions and status codes
4. Include authentication requirements if applicable