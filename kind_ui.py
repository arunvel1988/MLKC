from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import subprocess
import yaml
import json
import threading

app = Flask(__name__)

# Create a SQLite database to store cluster details
def create_database():
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS clusters
                 (name TEXT PRIMARY KEY, k8s_version TEXT, num_nodes INTEGER)''')
    conn.commit()
    conn.close()

# Check if a cluster with the same name already exists
def cluster_exists(name):
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM clusters WHERE name=?", (name,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

# Save cluster details to the database
def save_cluster(name, k8s_version, num_nodes):
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("INSERT INTO clusters VALUES (?, ?, ?)", (name, k8s_version, num_nodes))
    conn.commit()
    conn.close()

# Generate Kind cluster configuration YAML
def generate_kind_config(name, num_nodes):
    config = {
        "kind": "Cluster",
        "apiVersion": "kind.x-k8s.io/v1alpha4",
        "nodes": [{"role": "control-plane"}] + [{"role": "worker"} for _ in range(num_nodes - 1)]
    }
    with open(f"kind-config-{name}.yaml", "w") as file:
        yaml.dump(config, file)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/list_clusters')
def list_clusters():
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("SELECT * FROM clusters")
    db_clusters = c.fetchall()
    conn.close()

    # Get clusters using kind get clusters command
    kind_output = subprocess.check_output(['kind', 'get', 'clusters']).decode('utf-8')
    kind_clusters = kind_output.strip().split('\n') if kind_output.strip() else []

    return render_template('list_clusters.html', db_clusters=db_clusters, kind_clusters=kind_clusters)

@app.route('/create_cluster', methods=['GET', 'POST'])
def create_cluster():
    if request.method == 'POST':
        name = request.form['name']
        k8s_version = request.form['k8s_version']
        num_nodes = int(request.form['num_nodes'])

        if cluster_exists(name):
            error = f"Cluster with name '{name}' already exists."
            return render_template('create_cluster.html', error=error)

        # Generate Kind cluster configuration YAML
        generate_kind_config(name, num_nodes)

        # Create the Kind cluster
        try:
            subprocess.run(['kind', 'create', 'cluster', '--name', name,
                            '--image', f'kindest/node:v{k8s_version}',
                            '--config', f'kind-config-{name}.yaml'])
            save_cluster(name, k8s_version, num_nodes)
            return redirect(url_for('cluster_created', name=name))
        except subprocess.CalledProcessError as e:
            error = f"Error creating cluster: {str(e)}"
            return render_template('create_cluster.html', error=error)

    return render_template('create_cluster.html')

@app.route('/delete_cluster', methods=['POST'])
def delete_cluster():
    name = request.form['name']

    # Delete the Kind cluster
    try:
        result = subprocess.run(['kind', 'delete', 'cluster', '--name', name], check=True, capture_output=True, text=True)
        print(f"Kind cluster '{name}' deleted successfully.")
        print(f"Output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"Error deleting Kind cluster: {str(e)}")
        print(f"Output: {e.output}")
        # Handle the error appropriately (e.g., show an error message to the user)
        error_message = f"Failed to delete cluster '{name}'. Please check the logs for more information."
        return redirect(url_for('list_clusters', error=error_message))

    # Delete the cluster from the database
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("DELETE FROM clusters WHERE name=?", (name,))
    conn.commit()
    conn.close()

    success_message = f"Cluster '{name}' deleted successfully."
    return redirect(url_for('list_clusters', message=success_message))

@app.route('/cluster_info/<name>')
def cluster_info(name):
    # Get cluster information using kubectl
    try:
        # Change the Kubernetes context to the selected cluster
        context_name = f"kind-{name}"
        subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)

        # Get nodes
        nodes_output = subprocess.check_output(['kubectl', 'get', 'nodes', '-o', 'json']).decode('utf-8')
        nodes = json.loads(nodes_output)['items']
        nodes_data = []
        for node in nodes:
            nodes_data.append({
                'name': node['metadata']['name'],
                'status': node['status']['conditions'][-1]['type'],
                'roles': ','.join(node['metadata']['labels'].get('kubernetes.io/role', [])),
                'age': node['metadata']['creationTimestamp'],
                'version': node['status']['nodeInfo']['kubeletVersion']
            })

        # Get deployments
        deployments_output = subprocess.check_output(['kubectl', 'get', 'deployments', '-o', 'json']).decode('utf-8')
        deployments = json.loads(deployments_output)['items']
        deployments_data = []
        for deployment in deployments:
            ready_replicas = deployment['status'].get('readyReplicas', 'N/A')
            deployments_data.append({
                'name': deployment['metadata']['name'],
                'ready': f"{deployment['status']['readyReplicas']}/{deployment['spec']['replicas']}",
                'uptodate': deployment['status']['updatedReplicas'],
                'available': deployment['status']['availableReplicas'],
                'age': deployment['metadata']['creationTimestamp']
            })

        # Get pods
        pods_output = subprocess.check_output(['kubectl', 'get', 'pods', '-o', 'json']).decode('utf-8')
        pods = json.loads(pods_output)['items']
        pods_data = []
        for pod in pods:
            pods_data.append({
                'name': pod['metadata']['name'],
                'ready': f"{sum(container['ready'] for container in pod['status']['containerStatuses'])}/{len(pod['spec']['containers'])}",
                'status': pod['status']['phase'],
                'restarts': sum(container['restartCount'] for container in pod['status']['containerStatuses']),
                'age': pod['metadata']['creationTimestamp']
            })

        # Get services
        services_output = subprocess.check_output(['kubectl', 'get', 'services', '-o', 'json']).decode('utf-8')
        services = json.loads(services_output)['items']
        services_data = []
        for service in services:
            services_data.append({
                'name': service['metadata']['name'],
                'type': service['spec']['type'],
                'clusterip': service['spec']['clusterIP'],
                'externalip': ','.join(service['spec'].get('externalIPs', [])),
                'ports': ','.join(f"{port['port']}/{port['protocol']}" for port in service['spec']['ports']),
                'age': service['metadata']['creationTimestamp']
            })



        return render_template('cluster_info.html', name=name, nodes=nodes_data, deployments=deployments_data, pods=pods_data,
                               services=services_data)
    except subprocess.CalledProcessError as e:
        error = f"Error getting cluster information: {str(e)}"
        return render_template('cluster_info.html', name=name, error=error)
    

@app.route('/upload_yaml/<cluster_name>', methods=['GET', 'POST'])
def upload_yaml(cluster_name):
    if request.method == 'POST':
        if 'yaml_file' not in request.files:
            return redirect(url_for('cluster_info', name=cluster_name, error='No file uploaded'))

        file = request.files['yaml_file']

        if file.filename == '':
            return redirect(url_for('cluster_info', name=cluster_name, error='No file selected'))

        yaml_content = file.read().decode('utf-8')

        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            subprocess.run(['kubectl', 'apply', '-f', '-'], input=yaml_content.encode(), check=True)
            return redirect(url_for('cluster_info', name=cluster_name, message='Deployment successful'))
        except subprocess.CalledProcessError as e:
            error = f"Error deploying YAML: {str(e)}"
            return redirect(url_for('cluster_info', name=cluster_name, error=error))

    return render_template('upload_yaml.html', cluster_name=cluster_name)


def port_forward_thread(service_name, host_port, container_port):
    subprocess.run(['kubectl', 'port-forward', f'svc/{service_name}', f'{host_port}:{container_port}'], check=True)

@app.route('/port_forward/<cluster_name>', methods=['GET', 'POST'])
def port_forward(cluster_name):
    if request.method == 'POST':
        service_name = request.form['service_name']
        container_port = request.form['container_port']
        host_port = request.form['host_port']

        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            threading.Thread(target=port_forward_thread, args=(service_name, host_port, container_port)).start()
            message = f'http://localhost:{host_port}'
            return render_template('port_forward.html', cluster_name=cluster_name, message=message)
        except subprocess.CalledProcessError as e:
            error = f"Error during port forwarding: {str(e)}"
            return redirect(url_for('cluster_info', name=cluster_name, error=error))

    return render_template('port_forward.html', cluster_name=cluster_name)

@app.route('/cluster_created')
def cluster_created():
    name = request.args.get('name')
    return render_template('cluster_created.html', name=name)

if __name__ == '__main__':
    create_database()
    app.run(debug=True)