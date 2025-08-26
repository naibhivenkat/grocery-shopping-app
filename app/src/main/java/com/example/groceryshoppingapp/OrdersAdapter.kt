package com.example.groceryshoppingapp

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.models.Order

class OrdersAdapter(
    private val orders: List<Order>,
    private val onStatusClick: (Order) -> Unit
) : RecyclerView.Adapter<OrdersAdapter.OrderViewHolder>() {

    inner class OrderViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val orderId: TextView = view.findViewById(R.id.order_id)
        val orderDetails: TextView = view.findViewById(R.id.order_details)
        val statusButton: Button = view.findViewById(R.id.status_button)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): OrderViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_order_status, parent, false)
        return OrderViewHolder(view)
    }

    override fun onBindViewHolder(holder: OrderViewHolder, position: Int) {
        val order = orders[position]
        holder.orderId.text = "Order #${order.orderUuid}"
        holder.orderDetails.text = order.items.joinToString { "${it.quantity}×${it.item.name}" }

        holder.statusButton.text = order.status
        holder.statusButton.setOnClickListener {
            onStatusClick(order)
        }
    }

    override fun getItemCount(): Int = orders.size
}
