
Managed Local Kubernetes Kind Cluster (MLKC)

# Kind Cluster Management Application

This is a web-based application for managing Kubernetes clusters using Kind (Kubernetes in Docker). It provides a user-friendly interface to create, list, and delete Kind clusters, as well as view cluster information such as deployments, pods, and services.

## Features

- Create Kind clusters with specified name, Kubernetes version, and number of nodes
- List existing Kind clusters and their details
- Delete Kind clusters
- View cluster information, including deployments, pods, and services
- Attractive loading popup during cluster creation process

## Prerequisites

Before running the application, ensure that you have the following dependencies installed:

- Python (version X.X.X)
- Flask (version X.X.X)
- Kind (version X.X.X)
- kubectl (version X.X.X)

## Installation

1. Clone the repository:
2. Navigate to the project directory:
3. Install the required Python packages:
4. Set up the necessary environment variables (if applicable).

## Usage

1. Start the Flask application:
python3 kind_ui.py
2. Open a web browser and navigate to `http://localhost:5000`.

3. Use the provided interface to create, list, and delete Kind clusters.

4. Click on a cluster name to view detailed information about the cluster, including deployments, pods, and services.

## Configuration

The application uses a SQLite database to store cluster details. The database file is automatically created when the application starts.

You can customize the application by modifying the following files:

- `kind_ui.py`: Main Flask application file containing route definitions and cluster management logic.
- `templates/`: Directory containing HTML templates for different pages of the application.
- `static/`: Directory containing static assets such as CSS and JavaScript files <furture scope>

## Contributing

Contributions are welcome! If you find any issues or have suggestions for improvements, please open an issue or submit a pull request.


## Acknowledgements

- [Kind](https://kind.sigs.k8s.io/) - Kubernetes in Docker
- [Flask](https://flask.palletsprojects.com/) - Python web framework
- [Bootstrap](https://getbootstrap.com/) - CSS framework for responsive web design

## Contact

For any questions or inquiries, please contact csemanit2015@gmail.com

