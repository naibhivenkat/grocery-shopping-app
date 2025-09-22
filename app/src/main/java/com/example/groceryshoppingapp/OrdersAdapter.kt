package com.example.groceryshoppingapp
import android.content.Context;
import android.graphics.Color
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.models.Order

class OrdersAdapter(
    private val orders: List<Order>,
    private val onStatusClick: (Order) -> Unit,
    private val highlightCancelled: Boolean = true // 🔹 new optional flag
) : RecyclerView.Adapter<OrdersAdapter.OrderViewHolder>() {

    inner class OrderViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val orderId: TextView = view.findViewById(R.id.order_id)
        val orderDetails: TextView = view.findViewById(R.id.order_details)
        val statusButton: Button = view.findViewById(R.id.status_button)
        val txnIdText: TextView = view.findViewById(R.id.text_transaction_id)
        val container: View = view.findViewById(R.id.order_container)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): OrderViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_order_status, parent, false)
        return OrderViewHolder(view)
    }

    override fun onBindViewHolder(holder: OrderViewHolder, position: Int) {
        val order = orders[position]

        holder.orderId.text = "Order #${order.orderUuid}"
        val customerName = order.customer.fullName ?: order.customer.username
        val itemsText = order.items.joinToString { "${it.quantity}×${it.name}" }
        holder.orderDetails.text = "$customerName: $itemsText"

        // Transaction ID
        if (!order.transaction_id.isNullOrEmpty()) {
            holder.txnIdText.visibility = View.VISIBLE
            holder.txnIdText.text = "Txn ID: ${order.transaction_id}"
        } else {
            holder.txnIdText.visibility = View.GONE
        }

        // Status button
        holder.statusButton.text = order.status
        holder.statusButton.setBackgroundColor(getStatusColor(holder.statusButton.context, order.status))
        holder.statusButton.setTextColor(ContextCompat.getColor(holder.statusButton.context, android.R.color.white))

        // Container background - only if highlightCancelled is true
        val bgColorRes = if (highlightCancelled && order.status.equals("cancelled", true))
            R.color.order_bg_cancelled else R.color.order_bg
        holder.container.setBackgroundColor(ContextCompat.getColor(holder.container.context, bgColorRes))

        holder.statusButton.setOnClickListener {
            onStatusClick(order)
        }
    }

    override fun getItemCount(): Int = orders.size

    private fun getStatusColor(context: Context, status: String): Int {
        return when (status.lowercase()) {
            "pending" -> ContextCompat.getColor(context, R.color.orange_500)
            "packed" -> ContextCompat.getColor(context, R.color.blue_500)
            "delivered" -> ContextCompat.getColor(context, R.color.green_500)
            "cancelled" -> ContextCompat.getColor(context, R.color.red_500)
            else -> ContextCompat.getColor(context, android.R.color.darker_gray)
        }
    }
}

